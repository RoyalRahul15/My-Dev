"""Structured logging for the conversational service."""
from __future__ import annotations

import logging
import sys
from typing import Optional

_CONFIGURED = False


def _configure(level: str) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-26s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger("cai")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    _configure(level or "INFO")
    return logging.getLogger(f"cai.{name}")
