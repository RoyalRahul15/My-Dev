"""Central configuration for the Customer 360 multi-agent pipeline.

All tunables are read from environment variables with sensible defaults so the
same code runs unchanged across local, staging, and production. Nothing secret
is hard-coded here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings resolved once at process start."""

    # --- Database ---------------------------------------------------------
    # A pyodbc DSN or full connection string. Kept in the environment so
    # credentials never live in source control.
    odbc_dsn: str = field(default_factory=lambda: os.getenv("C360_ODBC_DSN", ""))
    db_schema: str = field(default_factory=lambda: os.getenv("C360_DB_SCHEMA", "iservedb"))

    # --- Feature window ---------------------------------------------------
    # Features are computed as-of this date; the target label looks forward
    # from it. Passed into every SQL builder.
    as_of_date: str = field(default_factory=lambda: os.getenv("C360_AS_OF_DATE", "2024-12-31"))
    min_date: str = field(default_factory=lambda: os.getenv("C360_MIN_DATE", "2022-01-01"))

    # --- Execution --------------------------------------------------------
    # Max feature agents run concurrently. Each gets its own DB connection,
    # so this also bounds the connection pool size.
    max_workers: int = field(default_factory=lambda: _get_int("C360_MAX_WORKERS", 6))
    # Per-agent retry attempts on transient DB failures.
    max_retries: int = field(default_factory=lambda: _get_int("C360_MAX_RETRIES", 3))
    retry_backoff_seconds: float = field(
        default_factory=lambda: float(os.getenv("C360_RETRY_BACKOFF", "2.0"))
    )

    # --- Join key ---------------------------------------------------------
    join_key: str = "serial_no"

    # --- Model artifacts --------------------------------------------------
    model_dir: str = field(default_factory=lambda: os.getenv("C360_MODEL_DIR", "./models"))

    # --- Output -----------------------------------------------------------
    output_dir: str = field(default_factory=lambda: os.getenv("C360_OUTPUT_DIR", "./output"))
    log_level: str = field(default_factory=lambda: os.getenv("C360_LOG_LEVEL", "INFO"))

    @property
    def as_of_sql(self) -> str:
        """As-of date quoted for direct interpolation into SQL."""
        return f"'{self.as_of_date}'"

    @property
    def min_date_sql(self) -> str:
        return f"'{self.min_date}'"

    def validate(self) -> None:
        """Fail fast at startup if required settings are missing."""
        if not self.odbc_dsn:
            raise ValueError(
                "C360_ODBC_DSN is not set. Provide a pyodbc DSN or connection string."
            )


# Singleton settings object imported across the package.
settings = Settings()
