"""Structured logging shared by every agent.

A single configured logger keeps agent output consistent and greppable in
production log aggregators. Import ``get_logger`` rather than calling
``logging.getLogger`` directly so formatting stays uniform.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

_CONFIGURED = False


def _configure_root(level: str) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger("c360")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """Return a namespaced logger under the ``c360`` root."""
    _configure_root(level or "INFO")
    return logging.getLogger(f"c360.{name}")
