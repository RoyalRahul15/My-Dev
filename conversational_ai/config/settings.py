"""Runtime configuration for the conversational AI service.

Everything is environment-driven so the same image runs across environments and
no credentials touch source control.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # --- LLM provider / gateway ------------------------------------------
    llm_provider: str = field(default_factory=lambda: os.getenv("CAI_LLM_PROVIDER", "anthropic"))
    llm_model: str = field(default_factory=lambda: os.getenv("CAI_LLM_MODEL", "claude-sonnet-5"))
    llm_fallback_model: str = field(
        default_factory=lambda: os.getenv("CAI_LLM_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    )
    llm_api_key: str = field(default_factory=lambda: os.getenv("CAI_LLM_API_KEY", ""))
    llm_timeout_s: float = field(default_factory=lambda: _float("CAI_LLM_TIMEOUT", 30.0))
    llm_max_retries: int = field(default_factory=lambda: _int("CAI_LLM_MAX_RETRIES", 2))
    llm_max_tokens: int = field(default_factory=lambda: _int("CAI_LLM_MAX_TOKENS", 1024))

    # --- Database (read-only analytics access) ---------------------------
    odbc_dsn: str = field(default_factory=lambda: os.getenv("CAI_ODBC_DSN", ""))
    db_schema: str = field(default_factory=lambda: os.getenv("CAI_DB_SCHEMA", "iservedb"))
    sql_row_limit: int = field(default_factory=lambda: _int("CAI_SQL_ROW_LIMIT", 100))
    sql_timeout_s: float = field(default_factory=lambda: _float("CAI_SQL_TIMEOUT", 20.0))

    # --- RAG / vector store ----------------------------------------------
    vector_store_url: str = field(default_factory=lambda: os.getenv("CAI_VECTOR_URL", ""))
    rag_top_k: int = field(default_factory=lambda: _int("CAI_RAG_TOP_K", 4))
    rag_min_score: float = field(default_factory=lambda: _float("CAI_RAG_MIN_SCORE", 0.35))

    # --- Guardrails -------------------------------------------------------
    enable_input_guardrails: bool = field(
        default_factory=lambda: os.getenv("CAI_INPUT_GUARDRAILS", "1") == "1"
    )
    enable_output_guardrails: bool = field(
        default_factory=lambda: os.getenv("CAI_OUTPUT_GUARDRAILS", "1") == "1"
    )
    max_input_chars: int = field(default_factory=lambda: _int("CAI_MAX_INPUT_CHARS", 2000))

    # --- Service ----------------------------------------------------------
    log_level: str = field(default_factory=lambda: os.getenv("CAI_LOG_LEVEL", "INFO"))

    def validate(self) -> None:
        if not self.llm_api_key:
            raise ValueError("CAI_LLM_API_KEY is not set.")


settings = Settings()
