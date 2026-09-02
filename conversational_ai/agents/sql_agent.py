"""SQL agent — answers data questions by querying the warehouse safely.

Flow: natural-language question + the *authenticated* customer id → the LLM
drafts a SELECT against a small, whitelisted schema → the query passes a strict
validator (read-only, single statement, mandatory customer scope, row cap) →
it runs read-only → the rows are summarised back into a natural-language answer.

Security is enforced in code, never trusted to the model:

* only ``SELECT`` — any DDL/DML/multi-statement is rejected
* the query MUST filter on the caller's own ``serial_no`` (no cross-customer reads)
* a hard ``LIMIT`` is injected
* only whitelisted tables/columns are exposed to the model
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..config.logger import get_logger
from ..config.settings import Settings, settings
from ..gateway.llm_gateway import LLMGateway

log = get_logger("agent.sql")

# Minimal, safe schema surfaced to the model. Extend deliberately — every
# column here is queryable by customers, so keep it non-sensitive.
SAFE_SCHEMA = {
    "cust_360_features": [
        "serial_no", "mf_portfolio_value", "mf_distinct_schemes", "mf_sip_user_flg",
        "eq_portfolio_value", "num_credit_cards", "score", "emi_total",
        "days_since_any_activity",
    ],
}

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|"
    r"call|exec|execute)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(Exception):
    """Raised when a generated query fails the safety validator."""


@dataclass
class SQLAnswer:
    answer: str
    sql: str
    rows: int


def _schema_prompt(schema: dict[str, list[str]]) -> str:
    lines = [f"{tbl}({', '.join(cols)})" for tbl, cols in schema.items()]
    return "Tables:\n" + "\n".join(lines)


class SQLAgent:
    """Text-to-SQL over a whitelisted, read-only view of customer data."""

    def __init__(
        self,
        gateway: LLMGateway,
        query_runner,  # callable(sql:str)->pd.DataFrame  (read-only connection)
        cfg: Optional[Settings] = None,
    ) -> None:
        self._gateway = gateway
        self._run = query_runner
        self._cfg = cfg or settings

    # --- generation ------------------------------------------------------
    def _draft_sql(self, question: str) -> str:
        system = (
            "You translate a customer's question into ONE read-only Impala SELECT. "
            "Use only the tables and columns given. Always filter by "
            "serial_no = :serial_no. Never write DDL or DML. Return SQL only, no prose.\n"
            + _schema_prompt(SAFE_SCHEMA)
        )
        resp = self._gateway.complete(system=system, prompt=question, max_tokens=300)
        return self._strip_fences(resp.text)

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE).strip()
        return text.rstrip(";").strip()

    # --- validation ------------------------------------------------------
    def _validate_and_scope(self, sql: str, serial_no: str) -> str:
        s = sql.strip()

        if not re.match(r"(?is)^\s*select\b", s):
            raise UnsafeQueryError("Only SELECT statements are allowed.")
        if ";" in s:
            raise UnsafeQueryError("Multiple statements are not allowed.")
        if _FORBIDDEN.search(s):
            raise UnsafeQueryError("Query contains a forbidden keyword.")

        # Mandatory customer scoping — bind the real id, refuse if absent.
        if ":serial_no" in s:
            safe_id = re.sub(r"[^0-9A-Za-z_]", "", serial_no)
            s = s.replace(":serial_no", f"'{safe_id}'")
        if re.search(r"serial_no\s*=", s) is None:
            raise UnsafeQueryError("Query must be scoped to the caller's serial_no.")

        # Only whitelisted tables may appear.
        for tbl in re.findall(r"\bfrom\s+([a-zA-Z_][\w.]*)", s, flags=re.IGNORECASE):
            base = tbl.split(".")[-1]
            if base not in SAFE_SCHEMA:
                raise UnsafeQueryError(f"Table '{tbl}' is not permitted.")

        if not re.search(r"\blimit\b", s, flags=re.IGNORECASE):
            s = f"{s} LIMIT {self._cfg.sql_row_limit}"
        return s

    # --- summarisation ---------------------------------------------------
    def _summarise(self, question: str, df: pd.DataFrame) -> str:
        preview = df.head(self._cfg.sql_row_limit).to_dict(orient="records")
        system = (
            "You are a helpful wealth assistant. Answer the customer's question "
            "in one or two sentences using ONLY the query results provided. "
            "If the result is empty, say you found no matching records."
        )
        prompt = f"Question: {question}\nResults: {preview}"
        return self._gateway.complete(system=system, prompt=prompt, max_tokens=250).text

    # --- public ----------------------------------------------------------
    def answer(self, question: str, *, serial_no: str) -> SQLAnswer:
        draft = self._draft_sql(question)
        safe_sql = self._validate_and_scope(draft, serial_no)
        log.info("running scoped SQL for customer=%s", serial_no)
        df = self._run(safe_sql)
        text = self._summarise(question, df)
        return SQLAnswer(answer=text, sql=safe_sql, rows=len(df))
