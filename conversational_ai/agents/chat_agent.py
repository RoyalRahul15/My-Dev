"""Chat agent — handles greetings and general conversation.

No DB, no retrieval — just a scoped, on-brand LLM reply. The system prompt keeps
it inside its lane: it introduces capabilities and politely redirects anything
that should really be a data or policy question.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ..config.settings import Settings, settings
from ..gateway.llm_gateway import LLMGateway

_SYSTEM = (
    "You are Aria, a friendly wealth-management assistant. Keep replies short and "
    "warm. You can help customers with (1) their own account data and (2) product "
    "and policy questions. If asked something outside that, gently steer back. "
    "Never give personalised financial advice or guarantee returns."
)


@dataclass
class ChatAnswer:
    answer: str


class ChatAgent:
    def __init__(self, gateway: LLMGateway, cfg: Optional[Settings] = None) -> None:
        self._gateway = gateway
        self._cfg = cfg or settings

    def answer(self, question: str, *, history: Sequence[str] = ()) -> ChatAnswer:
        context = ""
        if history:
            context = "Recent conversation:\n" + "\n".join(history[-6:]) + "\n\n"
        resp = self._gateway.complete(
            system=_SYSTEM, prompt=f"{context}Customer: {question}", max_tokens=250
        )
        return ChatAnswer(answer=resp.text)
