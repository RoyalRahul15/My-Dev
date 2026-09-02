"""Scoring agent — applies a trained propensity model to the master table.

Loads a versioned model artifact (joblib/pickle from the model registry) and
produces a 0-1 propensity score per customer. Kept model-agnostic: any
estimator exposing ``predict_proba`` works — logistic regression, random
forest, or XGBoost — so the production model can be swapped without touching
this code.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from ..config.settings import Settings, settings
from .base import Agent


class ScoringAgent(Agent[pd.DataFrame]):
    """Scores customers for one product's purchase propensity."""

    def __init__(
        self,
        product: str,
        model: Any | None = None,
        model_path: str | None = None,
        cfg: Settings | None = None,
    ) -> None:
        self.name = f"scoring.{product}"
        super().__init__()
        self._product = product
        self._cfg = cfg or settings
        self._model = model
        self._model_path = model_path

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        path = self._model_path or os.path.join(
            self._cfg.model_dir, f"propensity_{self._product}.joblib"
        )
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model artifact not found: {path}")
        import joblib  # imported lazily so training deps are optional at runtime

        self.log.info("loading model: %s", path)
        return joblib.load(path)

    def execute(self, *, master_df: pd.DataFrame, **_: object) -> pd.DataFrame:
        cfg = self._cfg
        model = self._load_model()

        key = cfg.join_key
        # Feature matrix: numeric columns only, excluding the key and any dates.
        feature_cols = [
            c for c in master_df.columns
            if c != key and pd.api.types.is_numeric_dtype(master_df[c])
        ]
        X = master_df[feature_cols].fillna(0)

        if not hasattr(model, "predict_proba"):
            raise TypeError("Loaded model does not support predict_proba().")

        scores = model.predict_proba(X)[:, 1]
        out = pd.DataFrame(
            {
                key: master_df[key].values,
                f"propensity_{self._product}": scores,
            }
        )
        self.log.info("scored %d customers for '%s'", len(out), self._product)
        return out
