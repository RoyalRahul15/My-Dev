"""Feature lookup — the live DATA handler when data is pre-computed.

When a customer asks about their own numbers, the answer already exists in the
online store (published by the batch job). So the right operation is a
millisecond **key lookup**, not live SQL against the warehouse.

:class:`FeatureLookupAgent` fetches the customer's record and turns the relevant
fields into a natural-language answer via the LLM gateway. It is the production
DATA path that closes the batch-to-serving gap: no warehouse on the request
path.

For genuinely fresh operational questions ("did my SIP debit today?") route to a
separate SQL agent over an operational read-replica — that's a different store
with different freshness, kept deliberately separate from this one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .logger import get_logger
from .online_store import OnlineStore

log = get_logger("feature_lookup")


class Summariser(Protocol):
    """Anything that turns (question, data) into a sentence — e.g. the LLM gateway."""

    def complete(self, *, system: str, prompt: str, max_tokens: int) -> object: ...


@dataclass
class LookupAnswer:
    answer: str
    found: bool
    fields_used: list[str]


_SYSTEM = (
    "You are a wealth assistant. Answer the customer's question in one or two "
    "sentences using ONLY the pre-computed feature values provided. If the "
    "relevant value is absent, say you don't have that detail on file. Never "
    "guess a number."
)


class FeatureLookupAgent:
    """Serves DATA questions from the online store (pre-computed features)."""

    def __init__(self, store: OnlineStore, summariser: Summariser) -> None:
        self._store = store
        self._summariser = summariser

    def answer(self, question: str, *, serial_no: str) -> LookupAnswer:
        record = self._store.get(serial_no)
        if not record:
            log.info("no online record for customer=%s", serial_no)
            return LookupAnswer(
                answer="I don't have your details on file yet. Please check back later.",
                found=False, fields_used=[],
            )

        # Hand the model only this customer's own pre-computed values.
        prompt = f"Question: {question}\nYour data: {record}"
        resp = self._summariser.complete(system=_SYSTEM, prompt=prompt, max_tokens=200)
        text = getattr(resp, "text", str(resp))
        return LookupAnswer(answer=text, found=True, fields_used=list(record.keys()))
