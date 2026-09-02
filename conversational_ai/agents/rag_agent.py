"""RAG agent — answers policy/product questions grounded in real documents.

Retrieves the top-k passages from the vector store, and answers strictly from
them. If nothing clears the similarity threshold, it declines rather than
inventing an answer — essential in a regulated domain. Every answer carries its
source citations so the response is auditable.

The vector store is injected via a small :class:`Retriever` protocol so this
works with Pinecone, FAISS, pgvector, or an in-memory store in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

from ..config.logger import get_logger
from ..config.settings import Settings, settings
from ..gateway.llm_gateway import LLMGateway

log = get_logger("agent.rag")


@dataclass
class Passage:
    text: str
    source: str
    score: float


class Retriever(Protocol):
    """Anything that can return scored passages for a query."""

    def search(self, query: str, top_k: int) -> Sequence[Passage]: ...


@dataclass
class RAGAnswer:
    answer: str
    citations: list[str] = field(default_factory=list)
    grounded: bool = True


_SYSTEM = (
    "You are a wealth-management policy assistant. Answer the question using ONLY "
    "the provided context passages. Cite the source of each fact as [source]. "
    "If the context does not contain the answer, say you don't have that "
    "information and suggest contacting the relationship manager. Never invent "
    "policy details, numbers, or fees."
)


class RAGAgent:
    def __init__(
        self,
        gateway: LLMGateway,
        retriever: Retriever,
        cfg: Optional[Settings] = None,
    ) -> None:
        self._gateway = gateway
        self._retriever = retriever
        self._cfg = cfg or settings

    def answer(self, question: str) -> RAGAnswer:
        cfg = self._cfg
        passages = [
            p for p in self._retriever.search(question, cfg.rag_top_k)
            if p.score >= cfg.rag_min_score
        ]

        if not passages:
            log.info("no passage cleared threshold %.2f; declining", cfg.rag_min_score)
            return RAGAnswer(
                answer=(
                    "I don't have that information in our policy documents. "
                    "Please reach out to your relationship manager for details."
                ),
                citations=[],
                grounded=False,
            )

        context = "\n\n".join(f"[{p.source}] {p.text}" for p in passages)
        prompt = f"Context:\n{context}\n\nQuestion: {question}"
        resp = self._gateway.complete(system=_SYSTEM, prompt=prompt, max_tokens=400)

        citations = sorted({p.source for p in passages})
        return RAGAnswer(answer=resp.text, citations=citations, grounded=True)
