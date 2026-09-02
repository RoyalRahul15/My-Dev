"""Entry point for the Customer 360 multi-agent pipeline.

Run the full batch:

    python -m customer360_agents.main

Configuration comes entirely from environment variables (see config/settings.py).
The orchestrator runs product feature agents in parallel, merges them onto the
customer anchor, then optionally scores and recommends.
"""
from __future__ import annotations

import os
import sys

from .agents import Orchestrator
from .config.settings import settings
from .utils.db import ConnectionFactory
from .utils.logger import get_logger

log = get_logger("main")


def main() -> int:
    try:
        settings.validate()
    except ValueError as err:
        log.error("configuration error: %s", err)
        return 2

    factory = ConnectionFactory()
    orchestrator = Orchestrator(factory=factory, cfg=settings)

    result = orchestrator.run(
        # Products to score once their trained models exist in settings.model_dir.
        score_products=(),
        # Product-holding flag columns for the recommender (fill when features land).
        recommend_flags=(),
    )

    if result.master_df is None:
        log.error("pipeline produced no master table")
        return 1

    os.makedirs(settings.output_dir, exist_ok=True)
    out_path = os.path.join(settings.output_dir, "master_features.parquet")
    result.master_df.to_parquet(out_path, index=False)
    log.info("wrote %s (%s)", out_path, result.master_df.shape)

    if result.failed_agents:
        log.warning("completed with failures: %s", result.failed_agents)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
