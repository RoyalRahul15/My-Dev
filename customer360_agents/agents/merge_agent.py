"""Merge agent — consolidates every product frame onto the customer anchor.

Starts from the Customer 360 base universe and left-joins each feature frame so
no customer is ever dropped. Missing product activity becomes 0 (meaningful:
"no activity"); date columns are coerced, not zero-filled.
"""
from __future__ import annotations

from functools import reduce
from typing import Sequence

import pandas as pd

from ..config.settings import Settings, settings
from ..sql import builders
from ..utils.db import ConnectionFactory, run_query_with_retry
from .base import Agent


class MergeAgent(Agent[pd.DataFrame]):
    """Left-merges all feature frames into a single master table."""

    name = "merge"

    def __init__(self, factory: ConnectionFactory, cfg: Settings | None = None) -> None:
        super().__init__()
        self._factory = factory
        self._cfg = cfg or settings

    def execute(self, *, feature_frames: Sequence[pd.DataFrame], **_: object) -> pd.DataFrame:
        cfg = self._cfg
        key = cfg.join_key

        # Anchor: the full customer universe.
        base = run_query_with_retry(self._factory, builders.base_serials(cfg))
        base[key] = base[key].astype(str).str.strip()
        self.log.info("anchor universe: %d customers", len(base))

        frames = [f for f in feature_frames if f is not None and not f.empty]
        if not frames:
            self.log.warning("no feature frames to merge; returning anchor only")
            return base

        master = reduce(
            lambda left, right: left.merge(right, on=key, how="left"),
            frames,
            base,
        )

        master = self._clean(master, key)
        self.log.info("master table: %s", master.shape)
        return master

    @staticmethod
    def _clean(df: pd.DataFrame, key: str) -> pd.DataFrame:
        """Coerce dates, zero-fill numeric gaps, and add cross-product recency."""
        date_cols = [c for c in df.columns if "date" in c.lower() or c.lower().endswith("_dt")]
        numeric_cols = [c for c in df.columns if c not in date_cols and c != key]

        # Numerics: coerce then fill absent activity with 0.
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

        # Dates: coerce bad values to NaT rather than crashing on comparison.
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors="coerce")

        if date_cols:
            df["latest_activity_date"] = df[date_cols].max(axis=1)
            df["days_since_any_activity"] = (
                pd.Timestamp("today").normalize() - df["latest_activity_date"]
            ).dt.days
        return df
