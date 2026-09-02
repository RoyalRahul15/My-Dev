"""Recommendation agent — next-best product via collaborative filtering.

Builds a customer x product holdings matrix, computes customer-to-customer
cosine similarity, and recommends products that similar customers hold but the
target customer does not. Deliberately dependency-light: only numpy.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from ..config.settings import Settings, settings
from .base import Agent


class RecommendationAgent(Agent[pd.DataFrame]):
    """Cosine-similarity collaborative filtering over product holdings."""

    name = "recommendation"

    def __init__(
        self,
        product_flag_cols: Sequence[str],
        top_k: int = 3,
        cfg: Settings | None = None,
    ) -> None:
        super().__init__()
        self._flags = list(product_flag_cols)
        self._top_k = top_k
        self._cfg = cfg or settings

    def execute(self, *, master_df: pd.DataFrame, **_: object) -> pd.DataFrame:
        key = self._cfg.join_key
        missing = [c for c in self._flags if c not in master_df.columns]
        if missing:
            raise ValueError(f"Missing product flag columns: {missing}")

        holdings = master_df[self._flags].to_numpy(dtype=float)
        holdings = (holdings > 0).astype(float)  # binarise: holds / does not hold

        # L2-normalise rows, then similarity = normalised dot product.
        norms = np.linalg.norm(holdings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        unit = holdings / norms

        # Product affinity = how strongly similar customers hold each product.
        # affinity[i, p] = sum_j sim(i, j) * holds(j, p)   (vectorised)
        affinity = unit @ (unit.T @ holdings)

        # Never recommend a product the customer already holds.
        affinity[holdings > 0] = -np.inf

        recommendations = []
        for idx in range(affinity.shape[0]):
            top = np.argsort(affinity[idx])[::-1][: self._top_k]
            recs = [self._flags[p] for p in top if np.isfinite(affinity[idx][p])]
            recommendations.append(recs)

        out = pd.DataFrame(
            {
                key: master_df[key].values,
                "recommended_products": recommendations,
            }
        )
        self.log.info("generated recommendations for %d customers", len(out))
        return out
