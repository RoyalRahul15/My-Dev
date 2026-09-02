"""SQL builders — one function per product feature set.

Each builder takes the runtime :class:`Settings` and returns a ready-to-run
Impala SQL string keyed on ``serial_no``. Keeping SQL here (not inside agents)
means the same query can be unit-tested, linted, and reused by batch or
ad-hoc jobs.

Only the two fully-optimised queries from this project (base universe, CIBIL,
Adobe campaign) are spelled out. The remaining product builders follow the
identical contract and are registered the same way — drop the optimised SQL
into each stub.
"""
from __future__ import annotations

from ..config.settings import Settings


def base_serials(s: Settings) -> str:
    """The customer anchor — every downstream feature left-joins onto this."""
    return f"""
    SELECT DISTINCT CAST(serial_no AS STRING) AS serial_no
    FROM {s.db_schema}.cust_360_new_wm_pwm_base_overall_1
    WHERE serial_no IS NOT NULL
    """


def cibil_features(s: Settings) -> str:
    """CIBIL credit features — optimised (26 CTEs -> 18, UNION + LEFT JOIN)."""
    return f"""
    WITH
    c360_serials AS (
        SELECT DISTINCT CAST(serial_no AS STRING) AS serial_no
        FROM {s.db_schema}.cust_360_new_wm_pwm_base_overall_1
        WHERE serial_no IS NOT NULL
    ),
    raw_cibil AS (
        SELECT *,
            REPLACE(REPLACE(
                REPLACE(REPLACE(REPLACE(memberreference,'PRP','9'),'"',''),'"',''),
            '"',''),'"','') AS member_id_clean
        FROM {s.db_schema}.cibil_account_details
        WHERE memberreference IS NOT NULL
    ),
    latest_dp AS (
        SELECT memberreference, MAX(dateprocessed) AS max_dateprocessed
        FROM raw_cibil GROUP BY memberreference
    ),
    base_latest AS (
        SELECT r.* FROM raw_cibil r
        JOIN latest_dp l ON r.memberreference = l.memberreference
                        AND r.dateprocessed  = l.max_dateprocessed
    ),
    base_latest_c360 AS (
        SELECT b.* FROM base_latest b
        JOIN c360_serials c ON b.member_id_clean = c.serial_no
    ),
    score_raw AS (
        SELECT
            REPLACE(REPLACE(
                REPLACE(REPLACE(REPLACE(memberreference,'PRP','9'),'"',''),'"',''),
            '"',''),'"','') AS member_id_clean,
            CAST(score AS DOUBLE) AS score_num, scoredate
        FROM {s.db_schema}.cibil_score_details
        WHERE memberreference IS NOT NULL AND score IS NOT NULL
    ),
    score_latest_dt AS (
        SELECT member_id_clean, MAX(scoredate) AS latest_scoredate
        FROM score_raw GROUP BY member_id_clean
    ),
    score_latest AS (
        SELECT sr.member_id_clean, MAX(sr.score_num) AS score
        FROM score_raw sr
        JOIN score_latest_dt sld ON sr.member_id_clean = sld.member_id_clean
                                AND sr.scoredate = sld.latest_scoredate
        JOIN c360_serials c ON sr.member_id_clean = c.serial_no
        GROUP BY sr.member_id_clean
    ),
    active_accounts AS (
        SELECT * FROM base_latest_c360 WHERE is_account_active = 1
    ),
    cc_feat AS (
        SELECT member_id_clean,
               COUNT(*) AS num_credit_cards,
               MIN(dateopeneddisbursed) AS open_card_since,
               SUM(credit_limit) AS total_credit_limit,
               MAX(credit_limit) AS max_credit_limit
        FROM active_accounts
        WHERE accounttype IN ('Credit Card','Secured Credit Card')
        GROUP BY member_id_clean
    ),
    cc_feat2 AS (
        SELECT member_id_clean,
               COALESCE(num_credit_cards, 0) AS num_credit_cards,
               COALESCE((YEAR(current_date()) - YEAR(open_card_since)) * 12
                        + (MONTH(current_date()) - MONTH(open_card_since)), 0)
                   AS months_since_card_open,
               COALESCE(total_credit_limit, 0) AS total_credit_limit,
               COALESCE(max_credit_limit, 0) AS max_credit_limit
        FROM cc_feat
    ),
    member_universe AS (
        SELECT member_id_clean FROM cc_feat2
        UNION
        SELECT member_id_clean FROM score_latest
    )
    SELECT
        mu.member_id_clean AS serial_no,
        COALESCE(cc.num_credit_cards, 0)       AS num_credit_cards,
        COALESCE(cc.months_since_card_open, 0) AS months_since_card_open,
        COALESCE(cc.total_credit_limit, 0)     AS total_credit_limit,
        COALESCE(cc.max_credit_limit, 0)       AS max_credit_limit,
        sl.score
    FROM member_universe mu
    LEFT JOIN cc_feat2     cc ON mu.member_id_clean = cc.member_id_clean
    LEFT JOIN score_latest sl ON mu.member_id_clean = sl.member_id_clean
    """


def adobe_campaign_features(s: Settings) -> str:
    """Adobe email-campaign engagement — optimised (INNER JOIN, CAST AS DATE)."""
    return f"""
    WITH
    c360_serials AS (
        SELECT DISTINCT CAST(serial_no AS BIGINT) AS serial_no
        FROM {s.db_schema}.cust_360_new_wm_pwm_base_overall_1
        WHERE serial_no IS NOT NULL
    ),
    customer_deliveries AS (
        SELECT DISTINCT
            CAST(cd.form_no AS BIGINT) AS form_no,
            cd.delivery_id, cd.id AS campaign_id,
            CAST(cd.event_date AS DATE) AS sent_date, 1 AS is_email_sent
        FROM {s.db_schema}.adobe_camp_del_log_rf cd
        INNER JOIN c360_serials c ON CAST(cd.form_no AS BIGINT) = c.serial_no
        WHERE cd.form_no IS NOT NULL
          AND TRIM(LOWER(cd.status)) = 'sent'
          AND TRIM(LOWER(cd.message_type)) = 'email'
          AND CAST(cd.event_date AS DATE) >= {s.min_date_sql}
          AND CAST(cd.event_date AS DATE) <= {s.as_of_sql}
    ),
    customer_tracking AS (
        SELECT DISTINCT
            CAST(ct.form_no AS BIGINT) AS form_no,
            ct.delivery_id, CAST(ct.log_date AS DATE) AS track_dt,
            TRIM(LOWER(ct.etype)) AS etype
        FROM {s.db_schema}.adobe_camp_track_log_rf ct
        INNER JOIN c360_serials c ON CAST(ct.form_no AS BIGINT) = c.serial_no
        WHERE ct.form_no IS NOT NULL
          AND TRIM(LOWER(ct.message_type)) = 'email'
          AND CAST(ct.log_date AS DATE) >= {s.min_date_sql}
          AND CAST(ct.log_date AS DATE) <= {s.as_of_sql}
          AND TRIM(LOWER(ct.etype)) IN
              ('open','mirror page','email click','click on mobile notification')
    ),
    delivery_level AS (
        SELECT cd.form_no, cd.delivery_id, cd.campaign_id, cd.sent_date, cd.is_email_sent,
            MAX(CASE WHEN ct.track_dt >= cd.sent_date
                      AND ct.etype IN ('open','mirror page') THEN 1 ELSE 0 END) AS has_opened,
            MAX(CASE WHEN ct.track_dt >= cd.sent_date
                      AND ct.etype IN ('email click','click on mobile notification')
                     THEN 1 ELSE 0 END) AS has_clicked
        FROM customer_deliveries cd
        LEFT JOIN customer_tracking ct
            ON cd.form_no = ct.form_no AND cd.delivery_id = ct.delivery_id
        GROUP BY cd.form_no, cd.delivery_id, cd.campaign_id, cd.sent_date, cd.is_email_sent
    ),
    customer_final_stats AS (
        SELECT form_no,
            COALESCE(SUM(has_opened) / NULLIF(CAST(SUM(is_email_sent) AS DOUBLE), 0.0), 0.0)
                AS email_open_rate,
            COALESCE(SUM(has_clicked) / NULLIF(CAST(SUM(is_email_sent) AS DOUBLE), 0.0), 0.0)
                AS email_click_rate,
            COALESCE(SUM(has_opened), 0) AS email_open_count
        FROM delivery_level GROUP BY form_no
    )
    SELECT
        CAST(form_no AS STRING) AS serial_no,
        COALESCE(email_open_rate, 0.0) * 100  AS email_open_rate,
        COALESCE(email_click_rate, 0.0) * 100 AS email_click_rate,
        COALESCE(email_open_count, 0)         AS email_open_count
    FROM customer_final_stats
    """


# --- Product builder stubs -----------------------------------------------
# Each follows the exact contract above: (Settings) -> SQL keyed on serial_no.
# Paste the optimised query body into each. Registering them wires them into
# the orchestrator automatically (see agents.feature_agents.build_feature_agents).

def mutual_fund_features(s: Settings) -> str:
    raise NotImplementedError("Drop the optimised agg_mf/pos_mf SQL here.")


def equity_features(s: Settings) -> str:
    raise NotImplementedError("Drop the optimised equity SQL here.")


def fno_features(s: Settings) -> str:
    raise NotImplementedError("Drop the optimised F&O (Part A + B merged) SQL here.")


def ipo_features(s: Settings) -> str:
    raise NotImplementedError("Drop the optimised features_ipo SQL here.")
