"""In-process settings cache — scope-aware, and deliberately NOT in the read path.

What this module is for
-----------------------
A per-process cache the settings resolver *could* consult before hitting the database.
It is written, tested and correct in itself, and nothing reads through it today.

Why it is not wired
-------------------
Settings decide money: the discount cap, the cash-movement limit, tax treatment, the
exchange window. A wrong value here is a wrong sale, not a slow page.

The invalidation available to us is the ``settings.changed`` outbox event consumed by
``SettingsConsumer``. That consumer runs in the worker process, so it can only clear the
cache of the process that received the event. With several API workers, a change made on
worker A leaves workers B..N serving the old value for up to ``_TTL_SECONDS`` (five
minutes) — long enough to sell at a retired discount cap or skip a tax rule.

The read path therefore queries the database per request, which is the correct trade
until invalidation is cross-process (a shared revision counter in Redis that every
worker checks, or an explicit version column read with the row). Wiring this cache
without that turns a correctness guarantee into a best-effort one.

Keying
------
Entries are keyed by ``(tenant, scope, scope_id, key)``, not ``(tenant, key)``. A
tenant-level read and a branch-level read of the same key are different answers, and the
old two-part key would have returned one for the other. Any future wiring must keep the
scope in the key: that is the whole point of this file's existence today.

``WIRED_INTO_READ_PATH`` records the decision in code, so a guard test can assert the
resolver still does not consult it and nobody assumes caching is happening.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

WIRED_INTO_READ_PATH = False

# Cache entry: (value, expires_at), keyed by (tenant, scope, scope_id, key).
_CACHE: dict[tuple[uuid.UUID, str, uuid.UUID | None, str], tuple[Any, float]] = {}

_TTL_SECONDS: float = 300.0  # 5 minutes


def _entry_key(
    tenant_id: uuid.UUID, scope: str, scope_id: uuid.UUID | None, key: str
) -> tuple[uuid.UUID, str, uuid.UUID | None, str]:
    return (tenant_id, scope, scope_id, key)


def get(tenant_id: uuid.UUID, scope: str, scope_id: uuid.UUID | None, key: str) -> Any | None:
    """Return the cached value for this exact scope if present and unexpired."""
    entry = _CACHE.get(_entry_key(tenant_id, scope, scope_id, key))
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        _CACHE.pop(_entry_key(tenant_id, scope, scope_id, key), None)
        return None
    return value


def put(
    tenant_id: uuid.UUID,
    scope: str,
    scope_id: uuid.UUID | None,
    key: str,
    value: Any,
) -> None:
    """Store a value for this exact scope with the standard TTL."""
    _CACHE[_entry_key(tenant_id, scope, scope_id, key)] = (value, time.monotonic() + _TTL_SECONDS)


def invalidate(tenant_id: uuid.UUID, key: str) -> int:
    """Remove every cached value for ``key`` across all scopes of this tenant."""
    to_remove = [k for k in _CACHE if k[0] == tenant_id and k[3] == key]
    for k in to_remove:
        _CACHE.pop(k, None)
    return len(to_remove)


def invalidate_scope(tenant_id: uuid.UUID, scope: str, scope_id: uuid.UUID | None) -> int:
    """Remove every cached value for one scope of this tenant."""
    to_remove = [k for k in _CACHE if k[0] == tenant_id and k[1] == scope and k[2] == scope_id]
    for k in to_remove:
        _CACHE.pop(k, None)
    return len(to_remove)


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
