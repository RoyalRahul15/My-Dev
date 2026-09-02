"""Online store — the bridge between the batch plane and live serving.

The batch pipeline computes features, propensity scores, and segments for all
customers offline. It *publishes* those results here. The conversational agent
then reads from here with a millisecond key lookup — it never touches the
analytical warehouse live.

Two backends behind one interface:

* :class:`InMemoryOnlineStore` — dev, tests, single-process.
* :class:`RedisOnlineStore`    — production: low-latency, TTL, horizontally
                                  scalable. Redis is imported lazily.

Keys are the customer ``serial_no``; values are a flat feature dict.
"""
from __future__ import annotations

import abc
import json
import time
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .logger import get_logger

log = get_logger("online_store")

FeatureRecord = Mapping[str, object]


@dataclass
class StoreStats:
    reads: int = 0
    writes: int = 0
    misses: int = 0


class OnlineStore(abc.ABC):
    """Key-value store of per-customer, pre-computed features."""

    def __init__(self) -> None:
        self.stats = StoreStats()

    @abc.abstractmethod
    def _get(self, serial_no: str) -> Optional[str]: ...

    @abc.abstractmethod
    def _set(self, serial_no: str, blob: str, ttl_s: Optional[int]) -> None: ...

    def get(self, serial_no: str) -> Optional[dict]:
        """Fetch one customer's feature record (or ``None`` if absent)."""
        blob = self._get(str(serial_no))
        self.stats.reads += 1
        if blob is None:
            self.stats.misses += 1
            return None
        return json.loads(blob)

    def put(self, serial_no: str, record: FeatureRecord, ttl_s: Optional[int] = None) -> None:
        """Write one customer's feature record."""
        self._set(str(serial_no), json.dumps(dict(record), default=str), ttl_s)
        self.stats.writes += 1

    def bulk_put(
        self, records: Iterable[tuple[str, FeatureRecord]], ttl_s: Optional[int] = None
    ) -> int:
        """Write many records. Backends may override for pipelining."""
        n = 0
        for serial_no, record in records:
            self.put(serial_no, record, ttl_s)
            n += 1
        return n


class InMemoryOnlineStore(OnlineStore):
    """Process-local store for dev and tests. Not shared across processes."""

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, tuple[str, Optional[float]]] = {}

    def _get(self, serial_no: str) -> Optional[str]:
        item = self._data.get(serial_no)
        if item is None:
            return None
        blob, expires_at = item
        if expires_at is not None and time.time() > expires_at:
            self._data.pop(serial_no, None)
            return None
        return blob

    def _set(self, serial_no: str, blob: str, ttl_s: Optional[int]) -> None:
        expires_at = time.time() + ttl_s if ttl_s else None
        self._data[serial_no] = (blob, expires_at)

    def __len__(self) -> int:
        return len(self._data)


class RedisOnlineStore(OnlineStore):
    """Production store backed by Redis (ElastiCache / Memorystore).

    Built for a real deployment: a shared **connection pool** (pods don't
    reconnect per request), **TLS**, bounded **socket timeouts** so a slow node
    fails fast, and **retry** to ride out a Multi-AZ failover promotion. Import
    is lazy so dev/test environments need no redis package.
    """

    def __init__(self, config: Optional["RedisConfig"] = None) -> None:  # noqa: F821
        super().__init__()
        import redis  # lazy
        from redis.backoff import ExponentialBackoff
        from redis.retry import Retry

        from .config import redis_config as _default_config

        cfg = config or _default_config
        self._prefix = cfg.key_prefix
        self._default_ttl = cfg.default_ttl_s

        pool = redis.connection.ConnectionPool.from_url(
            cfg.url(),
            decode_responses=True,
            max_connections=cfg.max_connections,
            socket_timeout=cfg.socket_timeout_s,
            socket_connect_timeout=cfg.socket_connect_timeout_s,
            retry=Retry(ExponentialBackoff(cap=0.5, base=0.05), cfg.retries),
            health_check_interval=30,
        )
        self._client = redis.Redis(connection_pool=pool)

    def _key(self, serial_no: str) -> str:
        return f"{self._prefix}{serial_no}"

    def ping(self) -> bool:
        """Liveness probe for readiness checks."""
        try:
            return bool(self._client.ping())
        except Exception:  # pragma: no cover
            log.warning("redis ping failed", exc_info=True)
            return False

    def _get(self, serial_no: str) -> Optional[str]:
        return self._client.get(self._key(serial_no))

    def _set(self, serial_no: str, blob: str, ttl_s: Optional[int]) -> None:
        self._client.set(self._key(serial_no), blob, ex=ttl_s or self._default_ttl)

    def bulk_put(self, records, ttl_s=None) -> int:  # pipelined for throughput
        ttl = ttl_s or self._default_ttl
        pipe = self._client.pipeline(transaction=False)
        n = 0
        for serial_no, record in records:
            pipe.set(self._key(str(serial_no)), json.dumps(dict(record), default=str), ex=ttl)
            n += 1
            if n % 1000 == 0:  # flush in chunks to bound memory
                pipe.execute()
                pipe = self._client.pipeline(transaction=False)
        pipe.execute()
        self.stats.writes += n
        return n
