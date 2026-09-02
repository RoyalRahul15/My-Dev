"""Conversation memory — short-term per-session context.

A minimal, thread-safe in-memory store keyed by session id. In production this
is swapped for Redis (TTL + horizontal scale) behind the same interface; the
orchestrator only depends on ``append`` and ``history``.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Deque, Dict, List


class ConversationMemory:
    def __init__(self, max_turns: int = 12) -> None:
        self._max = max_turns
        self._store: Dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=self._max))
        self._lock = threading.Lock()

    def append(self, session_id: str, role: str, text: str) -> None:
        with self._lock:
            self._store[session_id].append(f"{role}: {text}")

    def history(self, session_id: str) -> List[str]:
        with self._lock:
            return list(self._store.get(session_id, ()))

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)
