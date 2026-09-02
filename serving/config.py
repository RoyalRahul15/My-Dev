"""Production configuration for the online store.

Env-driven so the same image points at a local Redis in dev and a Multi-AZ
ElastiCache / Memorystore endpoint in production, with TLS and auth, without a
code change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class RedisConfig:
    """Connection + behaviour settings for the production Redis online store."""

    # Endpoint. In prod this is the ElastiCache/Memorystore primary DNS name.
    host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    port: int = field(default_factory=lambda: _int("REDIS_PORT", 6379))
    # AUTH token (ElastiCache) or password. Never hard-coded.
    password: str = field(default_factory=lambda: os.getenv("REDIS_PASSWORD", ""))
    # TLS in transit — on by default in production.
    use_tls: bool = field(default_factory=lambda: _bool("REDIS_TLS", True))

    # Connection pool — reused across requests so pods don't reconnect per call.
    max_connections: int = field(default_factory=lambda: _int("REDIS_MAX_CONNECTIONS", 50))
    socket_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("REDIS_SOCKET_TIMEOUT", "1.5"))
    )
    socket_connect_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("REDIS_CONNECT_TIMEOUT", "2.0"))
    )
    # Retry transient blips (failover promotion, brief network loss).
    retries: int = field(default_factory=lambda: _int("REDIS_RETRIES", 2))

    # Records auto-expire after the refresh window so stale data never lingers.
    default_ttl_s: int = field(default_factory=lambda: _int("REDIS_TTL_SECONDS", 90000))  # ~25h
    key_prefix: str = field(default_factory=lambda: os.getenv("REDIS_KEY_PREFIX", "c360:feat:"))

    def url(self) -> str:
        scheme = "rediss" if self.use_tls else "redis"
        auth = f":{self.password}@" if self.password else ""
        return f"{scheme}://{auth}{self.host}:{self.port}/0"


redis_config = RedisConfig()
