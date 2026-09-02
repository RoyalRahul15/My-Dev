"""Guardrails — safety checks on the way in and on the way out.

Input guardrails run before any model or DB call: length limits, prompt-injection
patterns, and blocking attempts to extract other customers' data. Output
guardrails run before the answer reaches the customer: PII redaction and a
block on unhedged financial advice (critical in a regulated domain).

These are deterministic, dependency-free checks — the fast first line. In
production they sit alongside a model-based layer (Llama Guard / NeMo
Guardrails); the :class:`GuardrailPipeline` interface is where that plugs in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..config.logger import get_logger
from ..config.settings import Settings, settings

log = get_logger("guardrails")


@dataclass
class GuardResult:
    allowed: bool
    text: str                       # possibly-transformed (redacted) text
    reason: Optional[str] = None
    flags: list[str] = field(default_factory=list)


# Prompt-injection / jailbreak signatures.
_INJECTION_PATTERNS = [
    r"ignore (all |the |your )?previous instructions",
    r"disregard (the |your )?(system|above)",
    r"you are now",
    r"reveal your (system )?prompt",
    r"act as (a |an )?(dan|jailbreak)",
]

# Attempts to reach data that isn't the caller's own.
_DATA_EXFIL_PATTERNS = [
    r"\ball customers\b",
    r"\bevery customer\b",
    r"other (customers|users|clients)",
    r"\bdump\b.*\b(table|database|records)\b",
]

# PII patterns for output redaction (India-centric + generic).
_PII_PATTERNS = {
    "pan": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "aadhaar": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "phone": r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b",
}

# Financial-advice phrasing that must carry a disclaimer.
_ADVICE_PATTERNS = [
    r"\byou should (buy|sell|invest)\b",
    r"\bguaranteed returns?\b",
    r"\bwill definitely (rise|grow|profit)\b",
]

_DISCLAIMER = (
    "\n\n_This is informational only and not financial advice. "
    "Please consult your relationship manager before investing._"
)


class InputGuardrail:
    """Validates and sanitises a customer utterance before processing."""

    def __init__(self, cfg: Optional[Settings] = None) -> None:
        self._cfg = cfg or settings

    def check(self, text: str) -> GuardResult:
        cfg = self._cfg
        stripped = (text or "").strip()

        if not stripped:
            return GuardResult(False, stripped, reason="empty_input")
        if len(stripped) > cfg.max_input_chars:
            return GuardResult(False, stripped, reason="input_too_long")

        low = stripped.lower()
        for pat in _INJECTION_PATTERNS:
            if re.search(pat, low):
                log.warning("blocked prompt injection: %s", pat)
                return GuardResult(False, stripped, reason="prompt_injection", flags=["injection"])
        for pat in _DATA_EXFIL_PATTERNS:
            if re.search(pat, low):
                log.warning("blocked data exfiltration attempt: %s", pat)
                return GuardResult(False, stripped, reason="data_exfiltration", flags=["exfil"])

        return GuardResult(True, stripped)


class OutputGuardrail:
    """Redacts PII and enforces advice disclaimers before the answer ships."""

    def check(self, text: str) -> GuardResult:
        redacted = text or ""
        flags: list[str] = []

        for label, pat in _PII_PATTERNS.items():
            if re.search(pat, redacted):
                redacted = re.sub(pat, f"[REDACTED_{label.upper()}]", redacted)
                flags.append(f"pii_{label}")

        low = redacted.lower()
        if any(re.search(p, low) for p in _ADVICE_PATTERNS) and "not financial advice" not in low:
            redacted += _DISCLAIMER
            flags.append("advice_disclaimer_added")

        return GuardResult(True, redacted, flags=flags or None or [])


class GuardrailPipeline:
    """Bundles input + output guardrails behind one object."""

    def __init__(self, cfg: Optional[Settings] = None) -> None:
        self._cfg = cfg or settings
        self.input = InputGuardrail(self._cfg)
        self.output = OutputGuardrail()

    def check_input(self, text: str) -> GuardResult:
        if not self._cfg.enable_input_guardrails:
            return GuardResult(True, (text or "").strip())
        return self.input.check(text)

    def check_output(self, text: str) -> GuardResult:
        if not self._cfg.enable_output_guardrails:
            return GuardResult(True, text)
        return self.output.check(text)
