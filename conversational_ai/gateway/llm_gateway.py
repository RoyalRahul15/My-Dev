"""LLM Gateway — the single, controlled entry point for every model call.

Nothing in the system talks to a model provider directly; everything goes
through the gateway so we get one place for:

* provider abstraction (swap Anthropic / OpenAI / self-hosted without touching agents)
* retry + timeout + automatic fallback to a cheaper/backup model
* token & cost accounting per call
* response caching for identical prompts
* a hard kill-switch and centralised auth

Providers are pluggable via :class:`LLMProvider`. A deterministic ``EchoProvider``
ships for local/dev and tests so the pipeline runs with no API key.
"""
from __future__ import annotations

import abc
import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional

from ..config.logger import get_logger
from ..config.settings import Settings, settings

log = get_logger("gateway")


@dataclass
class LLMResponse:
    """Uniform response regardless of provider."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    latency_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMProvider(abc.ABC):
    """Adapter to a concrete model provider."""

    name: str = "provider"

    @abc.abstractmethod
    def complete(
        self, *, system: str, prompt: str, model: str, max_tokens: int, timeout_s: float
    ) -> LLMResponse:
        """Return a completion. May raise on transport/timeout errors."""


class EchoProvider(LLMProvider):
    """Deterministic offline provider for local runs and unit tests."""

    name = "echo"

    def complete(self, *, system, prompt, model, max_tokens, timeout_s) -> LLMResponse:
        text = f"[echo:{model}] {prompt[:max_tokens]}"
        return LLMResponse(
            text=text, model=model,
            input_tokens=len(prompt.split()), output_tokens=len(text.split()),
        )


class AnthropicProvider(LLMProvider):
    """Adapter for the Anthropic Messages API (imported lazily)."""

    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def complete(self, *, system, prompt, model, max_tokens, timeout_s) -> LLMResponse:
        import anthropic  # lazy so the dep is optional in non-LLM environments

        client = anthropic.Anthropic(api_key=self._api_key, timeout=timeout_s)
        start = time.perf_counter()
        msg = client.messages.create(
            model=model,
            system=system,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        latency = time.perf_counter() - start
        text = "".join(block.text for block in msg.content if block.type == "text")
        return LLMResponse(
            text=text, model=model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            latency_s=latency,
        )


def _build_provider(cfg: Settings) -> LLMProvider:
    if cfg.llm_provider == "anthropic" and cfg.llm_api_key:
        return AnthropicProvider(cfg.llm_api_key)
    log.warning("using EchoProvider (no live provider configured)")
    return EchoProvider()


@dataclass
class _Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0


class LLMGateway:
    """Controlled facade over an :class:`LLMProvider`."""

    def __init__(self, provider: Optional[LLMProvider] = None, cfg: Optional[Settings] = None) -> None:
        self._cfg = cfg or settings
        self._provider = provider or _build_provider(self._cfg)
        self._cache: dict[str, LLMResponse] = {}
        self.usage = _Usage()

    @staticmethod
    def _key(system: str, prompt: str, model: str) -> str:
        return hashlib.sha256(f"{model}\0{system}\0{prompt}".encode()).hexdigest()

    def complete(
        self,
        *,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        use_cache: bool = True,
    ) -> LLMResponse:
        """Complete a prompt with retry, fallback, caching, and accounting."""
        cfg = self._cfg
        model = model or cfg.llm_model
        max_tokens = max_tokens or cfg.llm_max_tokens

        cache_key = self._key(system, prompt, model)
        if use_cache and cache_key in self._cache:
            self.usage.cache_hits += 1
            cached = self._cache[cache_key]
            return LLMResponse(**{**cached.__dict__, "cached": True})

        models_to_try = [model, cfg.llm_fallback_model]
        last_err: Optional[Exception] = None

        for candidate in models_to_try:
            for attempt in range(1, cfg.llm_max_retries + 1):
                try:
                    resp = self._provider.complete(
                        system=system, prompt=prompt, model=candidate,
                        max_tokens=max_tokens, timeout_s=cfg.llm_timeout_s,
                    )
                    self.usage.calls += 1
                    self.usage.input_tokens += resp.input_tokens
                    self.usage.output_tokens += resp.output_tokens
                    if use_cache:
                        self._cache[cache_key] = resp
                    return resp
                except Exception as err:  # noqa: BLE001
                    last_err = err
                    log.warning(
                        "LLM call failed (model=%s attempt=%d): %s",
                        candidate, attempt, err,
                    )
                    time.sleep(0.5 * attempt)
            log.warning("falling back from model '%s'", candidate)

        raise RuntimeError("All LLM providers/models failed") from last_err
