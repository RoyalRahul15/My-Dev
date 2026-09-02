"""Agent abstractions.

Every unit of work in the pipeline is an ``Agent`` with a uniform ``run``
contract, timing, and error capture. This makes the orchestrator agnostic to
what an agent actually does — feature extraction, merging, scoring, or
recommendation all look the same from the outside.
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

from ..utils.logger import get_logger

T = TypeVar("T")


@dataclass
class AgentResult(Generic[T]):
    """Outcome of a single agent run.

    Carries the payload on success or the error on failure, plus timing and a
    row count for observability. The orchestrator inspects ``ok`` to decide how
    to proceed without agents having to raise across thread boundaries.
    """

    name: str
    ok: bool
    payload: Optional[T] = None
    error: Optional[str] = None
    duration_s: float = 0.0
    rows: Optional[int] = None
    meta: dict[str, Any] = field(default_factory=dict)


class Agent(abc.ABC, Generic[T]):
    """Base class for all agents.

    Subclasses implement :meth:`execute`; the public :meth:`run` wraps it with
    timing, logging, and structured error handling so failures never crash a
    concurrent batch — they come back as a failed :class:`AgentResult`.
    """

    #: Human-readable, unique agent name used in logs and result keys.
    name: str = "agent"

    def __init__(self) -> None:
        self.log = get_logger(f"agent.{self.name}")

    @abc.abstractmethod
    def execute(self, **kwargs: Any) -> T:
        """Do the real work and return the payload. May raise."""

    def run(self, **kwargs: Any) -> AgentResult[T]:
        """Execute with timing and error capture. Never raises."""
        start = time.perf_counter()
        self.log.info("start")
        try:
            payload = self.execute(**kwargs)
            duration = time.perf_counter() - start
            rows = getattr(payload, "shape", [None])[0] if payload is not None else None
            self.log.info("done in %.2fs (rows=%s)", duration, rows)
            return AgentResult(
                name=self.name, ok=True, payload=payload, duration_s=duration, rows=rows
            )
        except Exception as err:  # noqa: BLE001 - captured intentionally
            duration = time.perf_counter() - start
            self.log.error("failed after %.2fs: %s", duration, err, exc_info=True)
            return AgentResult(
                name=self.name, ok=False, error=str(err), duration_s=duration
            )
