"""Database access layer for Impala over pyodbc.

Two hard-won rules from this codebase are enforced here:

1. Never use ``pandas.read_sql`` with pyodbc against Impala — it hangs. We drive
   the cursor directly via :func:`run_query`.
2. pyodbc connections are *not* thread-safe. When agents run in parallel, each
   worker must own its connection, so we expose a :class:`ConnectionFactory`
   rather than a shared connection.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

try:
    import pyodbc
except ImportError:  # pragma: no cover - allows import on machines without the driver
    pyodbc = None  # type: ignore

from ..config.settings import settings
from .logger import get_logger

log = get_logger("db")


def run_query(conn, sql: str) -> pd.DataFrame:
    """Execute ``sql`` on ``conn`` and return a DataFrame.

    Uses an explicit cursor + ``fetchall`` because ``pd.read_sql`` hangs with
    pyodbc on Impala. Column names are taken from the cursor description.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        # pyodbc rows are not plain tuples; normalise for pandas.
        return pd.DataFrame.from_records([tuple(r) for r in rows], columns=columns)
    finally:
        cursor.close()


class ConnectionFactory:
    """Creates fresh pyodbc connections on demand.

    Passed to every agent so each parallel worker opens its own connection and
    closes it when done — the safe pattern for a non-thread-safe driver.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.odbc_dsn
        if pyodbc is None:
            raise RuntimeError("pyodbc is not installed in this environment.")
        if not self._dsn:
            raise ValueError("No ODBC DSN configured; set C360_ODBC_DSN.")

    def connect(self):
        """Open and return a new connection. Caller owns closing it."""
        return pyodbc.connect(self._dsn, autocommit=True)

    @contextmanager
    def session(self) -> Iterator["pyodbc.Connection"]:
        """Context manager that opens a connection and guarantees close."""
        conn = self.connect()
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover - close is best-effort
                log.warning("Failed to close a DB connection cleanly.", exc_info=True)


def run_query_with_retry(
    factory: ConnectionFactory,
    sql: str,
    *,
    max_retries: int | None = None,
    backoff: float | None = None,
) -> pd.DataFrame:
    """Run ``sql`` on a fresh connection, retrying transient failures.

    A new connection is opened per attempt so a dropped link (Impala ``08S01``)
    self-heals on retry. Backoff is exponential.
    """
    attempts = max_retries if max_retries is not None else settings.max_retries
    base = backoff if backoff is not None else settings.retry_backoff_seconds
    last_err: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with factory.session() as conn:
                return run_query(conn, sql)
        except Exception as err:  # noqa: BLE001 - we re-raise after retries
            last_err = err
            if attempt == attempts:
                break
            wait = base * (2 ** (attempt - 1))
            log.warning(
                "Query failed (attempt %d/%d): %s — retrying in %.1fs",
                attempt, attempts, err, wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Query failed after {attempts} attempts") from last_err
