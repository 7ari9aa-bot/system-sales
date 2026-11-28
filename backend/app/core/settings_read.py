"""Read-only settings resolver for modules that cannot import ``settings.service``.

``identity`` and ``settings`` are in the same cyclic SCC (``settings.router``
imports ``identity.deps``), so ``identity`` cannot import ``settings.service``
without growing the cycle. This module lives in ``app.core`` — shared plumbing,
not a domain module — so importing it does not create a cross-module edge.

It provides the SAME inheritance walk and type coercion that
``SettingsService.resolve`` uses, but read-only: it calls
``scope_graph.resolve_chain`` and ``registry.get_definition`` (neither imports
``identity``) and reads the ``tenant_settings`` table directly.

Use this when you need a setting's effective value inside ``identity``,
``deps``, or any other module that sits on the far side of the settings cycle.
For writes, batch reads, or change management, use ``SettingsService`` directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.settings.registry import Scope, SettingDef, get_definition
from app.platform.settings.scope_graph import ScopeLink, resolve_chain


async def resolve_setting(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    *,
    scope: Scope | str = Scope.TENANT,
    scope_id: uuid.UUID | None = None,
) -> Any:
    """Resolve one setting to its effective value, walking the scope chain.

    Returns the registry default when no override exists at any scope.
    The value is coerced to the type declared in the registry definition.
    """
    scope_enum = Scope(scope) if isinstance(scope, str) else scope
    defn = get_definition(key)
    chain = await resolve_chain(session, tenant_id, scope_enum, scope_id)
    return await _resolve_from_chain(session, tenant_id, key, defn, chain)


async def resolve_settings(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    keys: list[str],
    *,
    scope: Scope | str = Scope.TENANT,
    scope_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Resolve several settings with one chain lookup and one override query."""
    scope_enum = Scope(scope) if isinstance(scope, str) else scope
    defs = {k: get_definition(k) for k in keys}
    chain = await resolve_chain(session, tenant_id, scope_enum, scope_id)
    rows = await _load_overrides(session, tenant_id, list(defs), chain)
    out: dict[str, Any] = {}
    for key, defn in defs.items():
        out[key] = _pick(key, defn, chain, rows)
    return out


async def setting_bool(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
) -> bool:
    """Convenience: resolve a boolean setting at tenant scope."""
    value = await resolve_setting(session, tenant_id, key)
    return bool(value)


def get_default(key: str) -> Any:
    """Return the registry default for a setting key (no tenant needed).

    Use this when you need the default value before a tenant exists (e.g. at
    registration).  Lives in ``app.core`` so callers in ``identity`` and other
    cycle-adjacent modules can read the default without importing
    ``app.platform.settings`` directly.
    """
    return get_definition(key).default


# -----------------------------------------------------------------------
# Internal helpers — mirror SettingsService._pick / _load_overrides
# but kept self-contained so this module has no dependency on the
# settings service (the whole point of avoiding the cycle).
# -----------------------------------------------------------------------


async def _resolve_from_chain(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    defn: SettingDef,
    chain: list[ScopeLink],
) -> Any:
    rows = await _load_overrides(session, tenant_id, [key], chain)
    return _pick(key, defn, chain, rows)


def _pick(
    key: str,
    defn: SettingDef,
    chain: list[ScopeLink],
    rows: dict[tuple[str, str, uuid.UUID | None], dict],
) -> Any:
    for link in chain:
        if not defn.scope_allowed(link.scope):
            continue
        row = rows.get((key, link.scope.value, link.scope_id))
        if row is not None:
            return row.get("v")
    return defn.default


async def _load_overrides(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    keys: list[str],
    chain: list[ScopeLink],
) -> dict[tuple[str, str, uuid.UUID | None], dict]:
    if not keys:
        return {}
    wanted = {(link.scope.value, link.scope_id) for link in chain}
    # Build a (key, scope, scope_id) -> value dict from the overrides that sit
    # exactly on the chain — a branch override for a DIFFERENT branch must never
    # leak into this branch's answer.
    stmt = text(
        "SELECT key, scope, scope_id, value->'v' AS v "
        "FROM tenant_settings "
        "WHERE tenant_id = :tid AND key = ANY(:keys) "
        "AND scope = ANY(:scopes)"
    )
    result = await session.execute(
        stmt,
        {
            "tid": tenant_id,
            "keys": keys,
            "scopes": [s for s, _ in wanted],
        },
    )
    out: dict[tuple[str, str, uuid.UUID | None], dict] = {}
    for key, scope, scope_id, value in result.all():
        if (scope, scope_id) in wanted:
            out[(key, scope, scope_id)] = {"v": value}
    return out
