"""Feature agents — one specialist per product line.

A :class:`FeatureAgent` pairs a product name with a SQL builder. It runs the
query on its own connection (safe for parallel execution), normalises the join
key to string, and returns a customer-level DataFrame. Adding a new product is
one registry entry — nothing else in the pipeline changes.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from ..config.settings import Settings, settings
from ..sql import builders
from ..utils.db import ConnectionFactory, run_query_with_retry
from .base import Agent

SqlBuilder = Callable[[Settings], str]


class FeatureAgent(Agent[pd.DataFrame]):
    """Runs one product's SQL and returns customer-level features."""

    def __init__(
        self,
        name: str,
        sql_builder: SqlBuilder,
        factory: ConnectionFactory,
        cfg: Settings | None = None,
    ) -> None:
        self.name = name
        super().__init__()
        self._build = sql_builder
        self._factory = factory
        self._cfg = cfg or settings

    def execute(self, **_: object) -> pd.DataFrame:
        sql = self._build(self._cfg)
        df = run_query_with_retry(self._factory, sql)

        key = self._cfg.join_key
        if key not in df.columns:
            raise ValueError(
                f"Agent '{self.name}' output is missing join key '{key}'. "
                f"Columns: {list(df.columns)}"
            )
        # Normalise the key so every agent's frame merges cleanly.
        df[key] = df[key].astype(str).str.strip()
        return df


# --- Registry -------------------------------------------------------------
# Product name -> SQL builder. Only fully-optimised, runnable queries are
# enabled by default; stubs are listed but commented until their SQL lands.
FEATURE_REGISTRY: dict[str, SqlBuilder] = {
    "cibil": builders.cibil_features,
    "adobe_campaign": builders.adobe_campaign_features,
    # "mutual_fund": builders.mutual_fund_features,
    # "equity": builders.equity_features,
    # "fno": builders.fno_features,
    # "ipo": builders.ipo_features,
}


def build_feature_agents(
    factory: ConnectionFactory, cfg: Settings | None = None
) -> list[FeatureAgent]:
    """Instantiate a :class:`FeatureAgent` for every registered product."""
    return [
        FeatureAgent(name, builder, factory, cfg)
        for name, builder in FEATURE_REGISTRY.items()
    ]
