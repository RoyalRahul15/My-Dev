"""Intent router — decides which agent answers a given question.

Three destinations:

* ``DATA``   → the customer is asking about their own numbers/holdings/activity
               → SQL agent queries the warehouse.
* ``POLICY`` → the customer is asking about products, rules, or documents
               → RAG agent retrieves from the policy knowledge base.
* ``CHAT``   → greetings, small talk, anything else → plain LLM conversation.

A fast rule-based pass handles the obvious cases cheaply; ambiguous ones fall
back to an LLM classification through the gateway, so routing itself is robust
without paying for a model call on every message.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..config.logger import get_logger
from ..gateway.llm_gateway import LLMGateway

log = get_logger("router")


class Intent(str, Enum):
    DATA = "data"
    POLICY = "policy"
    CHAT = "chat"


@dataclass
class RouteDecision:
    intent: Intent
    confidence: float
    method: str  # "rule" or "llm"


_DATA_HINTS = [
    r"\bmy (portfolio|holdings?|balance|aum|sip|transactions?|returns?|score)\b",
    r"\bhow much\b", r"\bhow many\b",
    r"\bwhat('| i)s my\b", r"\bshow me my\b",
    r"\blast (month|quarter|year)\b",
    r"\b(invested|redeemed|traded|bought|sold)\b",
]

_POLICY_HINTS = [
    r"\bpolicy\b", r"\bpolicies\b", r"\bterms\b", r"\bcharges?\b", r"\bfees?\b",
    r"\beligibility\b", r"\bhow do i\b", r"\bwhat is (a |an |the )?\b",
    r"\bexit load\b", r"\block[- ]?in\b", r"\btax\b", r"\bkyc\b", r"\bnominee\b",
    r"\bhow does .* work\b",
]

_CHAT_HINTS = [
    r"^\s*(hi|hello|hey|thanks|thank you|good (morning|evening|afternoon))\b",
    r"\bwho are you\b", r"\bwhat can you do\b",
]

_CLASSIFY_SYSTEM = (
    "You are an intent classifier for a wealth-management assistant. "
    "Reply with exactly one word: DATA, POLICY, or CHAT. "
    "DATA = the user asks about their own account numbers/holdings/activity. "
    "POLICY = the user asks about products, rules, fees, or documentation. "
    "CHAT = greetings or small talk."
)


class IntentRouter:
    def __init__(self, gateway: Optional[LLMGateway] = None) -> None:
        self._gateway = gateway

    def route(self, text: str) -> RouteDecision:
        low = text.lower().strip()

        if any(re.search(p, low) for p in _CHAT_HINTS):
            return RouteDecision(Intent.CHAT, 0.9, "rule")
        if any(re.search(p, low) for p in _DATA_HINTS):
            return RouteDecision(Intent.DATA, 0.8, "rule")
        if any(re.search(p, low) for p in _POLICY_HINTS):
            return RouteDecision(Intent.POLICY, 0.8, "rule")

        # Ambiguous — ask the model, if we have a gateway.
        if self._gateway is not None:
            resp = self._gateway.complete(
                system=_CLASSIFY_SYSTEM, prompt=text, max_tokens=4, use_cache=True
            )
            label = resp.text.strip().upper()
            for intent in Intent:
                if intent.name in label:
                    return RouteDecision(intent, 0.6, "llm")

        # Safe default: treat as policy (RAG grounds the answer in real docs).
        return RouteDecision(Intent.POLICY, 0.4, "rule")
