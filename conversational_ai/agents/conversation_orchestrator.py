"""Conversation orchestrator — the brain that ties everything together.

For every customer message it runs the full production path:

    input guardrail → route → (SQL | RAG | Chat) agent → output guardrail → memory

Each stage is defensive: a blocked input returns a safe refusal, an agent error
degrades to a graceful fallback message, and the output guardrail always runs
before anything reaches the customer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config.logger import get_logger
from ..config.settings import Settings, settings
from ..gateway.llm_gateway import LLMGateway
from ..guardrails.guardrails import GuardrailPipeline
from ..memory.conversation_memory import ConversationMemory
from ..router.intent_router import Intent, IntentRouter
from .chat_agent import ChatAgent
from .rag_agent import RAGAgent, Retriever
from .sql_agent import SQLAgent, UnsafeQueryError

log = get_logger("orchestrator")


@dataclass
class Reply:
    text: str
    intent: str
    citations: list[str] = field(default_factory=list)
    sql: Optional[str] = None
    blocked: bool = False
    flags: list[str] = field(default_factory=list)


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        gateway: LLMGateway,
        retriever: Retriever,
        query_runner,
        memory: Optional[ConversationMemory] = None,
        cfg: Optional[Settings] = None,
    ) -> None:
        self._cfg = cfg or settings
        self._gateway = gateway
        self._guard = GuardrailPipeline(self._cfg)
        self._router = IntentRouter(gateway)
        self._sql = SQLAgent(gateway, query_runner, self._cfg)
        self._rag = RAGAgent(gateway, retriever, self._cfg)
        self._chat = ChatAgent(gateway, self._cfg)
        self._memory = memory or ConversationMemory()

    def handle(self, *, session_id: str, serial_no: str, message: str) -> Reply:
        # 1. Input guardrail -------------------------------------------------
        gi = self._guard.check_input(message)
        if not gi.allowed:
            log.warning("input blocked (%s) session=%s", gi.reason, session_id)
            return Reply(
                text="I'm sorry, I can't help with that request.",
                intent="blocked", blocked=True, flags=gi.flags,
            )
        clean = gi.text
        self._memory.append(session_id, "customer", clean)

        # 2. Route -----------------------------------------------------------
        decision = self._router.route(clean)
        log.info("routed to %s (%.2f, %s)", decision.intent, decision.confidence, decision.method)

        # 3. Dispatch --------------------------------------------------------
        citations: list[str] = []
        sql: Optional[str] = None
        try:
            if decision.intent is Intent.DATA:
                res = self._sql.answer(clean, serial_no=serial_no)
                raw, sql = res.answer, res.sql
            elif decision.intent is Intent.POLICY:
                res = self._rag.answer(clean)
                raw, citations = res.answer, res.citations
            else:
                res = self._chat.answer(clean, history=self._memory.history(session_id))
                raw = res.answer
        except UnsafeQueryError as err:
            log.warning("unsafe SQL blocked: %s", err)
            raw = "I can only answer questions about your own account details."
        except Exception as err:  # noqa: BLE001 - graceful degradation
            log.error("agent error: %s", err, exc_info=True)
            raw = "Something went wrong on my end. Please try again in a moment."

        # 4. Output guardrail ------------------------------------------------
        go = self._guard.check_output(raw)
        self._memory.append(session_id, "assistant", go.text)

        return Reply(
            text=go.text,
            intent=decision.intent.value,
            citations=citations,
            sql=sql,
            flags=go.flags,
        )
