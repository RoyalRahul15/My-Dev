"""Orchestrator — coordinates the whole pipeline.

Runs feature agents concurrently (each on its own connection), collects their
results with per-agent fault isolation, then hands the surviving frames through
merge -> score -> recommend. One failed product never sinks the run; it is
logged and the pipeline proceeds with what succeeded.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import pandas as pd

from ..config.settings import Settings, settings
from ..utils.db import ConnectionFactory
from ..utils.logger import get_logger
from .base import AgentResult
from .feature_agents import FeatureAgent, build_feature_agents
from .merge_agent import MergeAgent
from .recommendation_agent import RecommendationAgent
from .scoring_agent import ScoringAgent


@dataclass
class PipelineResult:
    """Everything a run produces, plus the audit trail of agent outcomes."""

    master_df: Optional[pd.DataFrame] = None
    scores: dict[str, pd.DataFrame] = field(default_factory=dict)
    recommendations: Optional[pd.DataFrame] = None
    agent_results: list[AgentResult] = field(default_factory=list)

    @property
    def failed_agents(self) -> list[str]:
        return [r.name for r in self.agent_results if not r.ok]


class Orchestrator:
    """Top-level coordinator for the feature -> model -> serve pipeline."""

    def __init__(
        self,
        factory: ConnectionFactory | None = None,
        cfg: Settings | None = None,
    ) -> None:
        self._cfg = cfg or settings
        self._factory = factory or ConnectionFactory()
        self.log = get_logger("orchestrator")

    # --- Stage 1: features (parallel) ------------------------------------
    def run_feature_agents(
        self, agents: Sequence[FeatureAgent] | None = None
    ) -> tuple[list[pd.DataFrame], list[AgentResult]]:
        agents = list(agents or build_feature_agents(self._factory, self._cfg))
        self.log.info("running %d feature agents (max_workers=%d)",
                      len(agents), self._cfg.max_workers)

        results: list[AgentResult] = []
        frames: list[pd.DataFrame] = []

        with ThreadPoolExecutor(max_workers=self._cfg.max_workers) as pool:
            futures = {pool.submit(a.run): a.name for a in agents}
            for fut in as_completed(futures):
                res = fut.result()  # AgentResult; run() never raises
                results.append(res)
                if res.ok and res.payload is not None:
                    frames.append(res.payload)
                else:
                    self.log.error("feature agent '%s' failed: %s", res.name, res.error)

        self.log.info("feature stage: %d/%d succeeded", len(frames), len(agents))
        return frames, results

    # --- Full pipeline ----------------------------------------------------
    def run(
        self,
        *,
        score_products: Sequence[str] = (),
        recommend_flags: Sequence[str] = (),
    ) -> PipelineResult:
        """Execute features -> merge -> (optional) score -> (optional) recommend."""
        result = PipelineResult()

        frames, feat_results = self.run_feature_agents()
        result.agent_results.extend(feat_results)

        merge_res = MergeAgent(self._factory, self._cfg).run(feature_frames=frames)
        result.agent_results.append(merge_res)
        if not merge_res.ok:
            self.log.error("merge failed; aborting pipeline")
            return result
        result.master_df = merge_res.payload

        for product in score_products:
            score_res = ScoringAgent(product, cfg=self._cfg).run(master_df=result.master_df)
            result.agent_results.append(score_res)
            if score_res.ok and score_res.payload is not None:
                result.scores[product] = score_res.payload

        if recommend_flags:
            rec_res = RecommendationAgent(recommend_flags, cfg=self._cfg).run(
                master_df=result.master_df
            )
            result.agent_results.append(rec_res)
            if rec_res.ok:
                result.recommendations = rec_res.payload

        self._log_summary(result)
        return result

    def _log_summary(self, result: PipelineResult) -> None:
        failed = result.failed_agents
        total = len(result.agent_results)
        self.log.info("pipeline complete: %d/%d agents ok", total - len(failed), total)
        if failed:
            self.log.warning("failed agents: %s", ", ".join(failed))
