"""Publisher — the last step of the batch pipeline.

Takes the batch outputs (master feature table, propensity scores, segment
labels) and writes one consolidated record per customer into the online store.
After this runs, the live conversational agent can serve every customer with a
single fast key lookup — no warehouse access on the request path.

Run it at the end of the nightly job, right after scoring.
"""
from __future__ import annotations

from typing import Mapping, Optional

import pandas as pd

from .logger import get_logger
from .online_store import OnlineStore

log = get_logger("publisher")


class Publisher:
    """Consolidates batch outputs and publishes them to the online store."""

    def __init__(self, store: OnlineStore, key: str = "serial_no") -> None:
        self._store = store
        self._key = key

    def publish(
        self,
        master_df: pd.DataFrame,
        *,
        scores: Optional[Mapping[str, pd.DataFrame]] = None,
        segments: Optional[pd.DataFrame] = None,
        ttl_s: Optional[int] = None,
    ) -> int:
        """Merge features + scores + segments and write one record per customer.

        ``scores`` maps product -> DataFrame[serial_no, propensity_<product>].
        ``segments`` is DataFrame[serial_no, segment] (the persona label).
        Returns the number of records published.
        """
        key = self._key
        if key not in master_df.columns:
            raise ValueError(f"master_df missing key column '{key}'")

        wide = master_df.copy()
        wide[key] = wide[key].astype(str)

        # Fold in propensity scores.
        for product, sdf in (scores or {}).items():
            sdf = sdf.copy()
            sdf[key] = sdf[key].astype(str)
            wide = wide.merge(sdf, on=key, how="left")

        # Fold in the segment/persona label.
        if segments is not None:
            seg = segments.copy()
            seg[key] = seg[key].astype(str)
            wide = wide.merge(seg, on=key, how="left")

        # One JSON-serialisable record per customer.
        records = (
            (row[key], {c: row[c] for c in wide.columns if c != key})
            for _, row in wide.iterrows()
        )
        n = self._store.bulk_put(records, ttl_s=ttl_s)
        log.info("published %d customer records to online store", n)
        return n
