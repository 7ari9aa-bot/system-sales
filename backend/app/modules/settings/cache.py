"""In-process settings cache — invalidated by the ``settings.changed`` consumer.

A lightweight, per-tenant LRU-like cache that the settings resolver can consult
before hitting the database.  The cache is populated on read (miss → DB → fill)
and invalidated by the ``SettingsConsumer`` worker when a ``settings.changed``
event arrives on the outbox stream.

The cache is intentionally simple:
* process-local (no cross-process invalidation; each worker process has its own);
* TTL-bounded (entries expire after ``_TTL_SECONDS`` even if no event arrives);
* best-effort (a cache miss falls through to the DB — correctness never
  depends on the cache being warm).

The consumer calls :func:`invalidate` with the ``(tenant_id, key)`` pair from
the event payload.  A tenant-wide flush (all keys) is available for full
rebuilds.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

# Cache entry: (value, expires_at).
_CACHE: dict[tuple[uuid.UUID, str], tuple[Any, float]] = {}

_TTL_SECONDS: float = 300.0  # 5 minutes


def get(tenant_id: uuid.UUID, key: str) -> Any | None:
    """Return the cached value if present and not expired, else ``None``."""
    entry = _CACHE.get((tenant_id, key))
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        _CACHE.pop((tenant_id, key), None)
        return None
    return value


def put(tenant_id: uuid.UUID, key: str, value: Any) -> None:
    """Store a value in the cache with the standard TTL."""
    _CACHE[(tenant_id, key)] = (value, time.monotonic() + _TTL_SECONDS)


def invalidate(tenant_id: uuid.UUID, key: str) -> None:
    """Remove one ``(tenant_id, key)`` entry from the cache."""
    _CACHE.pop((tenant_id, key), None)


def invalidate_tenant(tenant_id: uuid.UUID) -> int:
    """Remove **all** entries for a tenant.  Returns the number removed."""
    to_remove = [k for k in _CACHE if k[0] == tenant_id]
    for k in to_remove:
        _CACHE.pop(k, None)
    return len(to_remove)


def clear() -> None:
    """Drop the entire cache (for tests)."""
    _CACHE.clear()


def size() -> int:
    """Number of entries currently in the cache (for tests)."""
    return len(_CACHE)
