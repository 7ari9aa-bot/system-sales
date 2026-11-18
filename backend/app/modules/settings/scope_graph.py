"""Scope graph: where each scope entity sits in the tenant's real hierarchy.

The resolver must never trust the caller to say "this register belongs to that
profile". It asks the database. The parent links are the ones the operational
tables already carry:

    register.profile_id    -> pos_profile
    pos_profile.warehouse_id -> warehouse
    warehouse.location_id  -> branch (a ``locations`` row)
    branch                 -> tenant

A scope id that does not exist for the tenant is an error (``UnknownScopeError``),
not an empty chain: otherwise any random UUID would be accepted as a scope and a
typo would silently fall back to the tenant value.

``channel`` is a name (``pos``, ``website``, ``whatsapp``), not a row, so its
``scope_id`` is a *warehouse* id plus the channel name carried by the caller. A
channel-level override is therefore stored as scope ``channel`` with the
warehouse that serves it as ``scope_id`` and the channel name inside the key's
value namespace; see ``SettingsService`` for how it resolves.

All reads here go through the tenant-bound session, so RLS applies a second time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import NotFoundError
from app.modules.settings.registry import Scope


class UnknownScopeError(NotFoundError):
    """The scope entity does not exist for this tenant."""


@dataclass(frozen=True, slots=True)
class ScopeLink:
    """One hop of a resolved chain: a scope and the entity id (None = tenant)."""

    scope: Scope
    scope_id: uuid.UUID | None


# (table, scope the table represents, parent scope, column holding the parent id)
_PARENT_COLUMN: dict[Scope, tuple[str, Scope, str]] = {
    Scope.REGISTER: ("pos_registers", Scope.POS_PROFILE, "profile_id"),
    Scope.POS_PROFILE: ("pos_profiles", Scope.WAREHOUSE, "warehouse_id"),
    Scope.WAREHOUSE: ("warehouses", Scope.BRANCH, "location_id"),
}

# Tables whose primary key IS the scope id, for scopes with no parent column.
_ROOT_TABLE: dict[Scope, str] = {
    Scope.BRANCH: "locations",
    Scope.WAREHOUSE: "warehouses",
    Scope.POS_PROFILE: "pos_profiles",
    Scope.REGISTER: "pos_registers",
    Scope.USER: "tenant_users",
}


async def _exists(session: AsyncSession, scope: Scope, scope_id: uuid.UUID, tenant_id) -> bool:
    table = _ROOT_TABLE.get(scope)
    if table is None:
        return False
    if scope is Scope.USER:
        sql = f"SELECT 1 FROM {table} WHERE tenant_id = :tid AND user_id = :sid"  # noqa: S608
    else:
        sql = f"SELECT 1 FROM {table} WHERE tenant_id = :tid AND id = :sid"  # noqa: S608
    row = await session.execute(text(sql), {"tid": tenant_id, "sid": scope_id})
    return row.first() is not None


async def require_scope_entity(
    session: AsyncSession, tenant_id: uuid.UUID, scope: Scope, scope_id: uuid.UUID | None
) -> None:
    """Raise if ``scope_id`` is missing, or not a row of this tenant, for ``scope``."""
    if scope is Scope.TENANT:
        if scope_id is not None:
            raise UnknownScopeError("tenant scope takes no scope_id")
        return
    if scope_id is None:
        raise UnknownScopeError(f"scope {scope.value!r} requires a scope_id")
    if scope is Scope.CHANNEL:
        # A channel override hangs on the warehouse that serves the channel.
        scope = Scope.WAREHOUSE
    if not await _exists(session, scope, scope_id, tenant_id):
        raise UnknownScopeError(f"{scope.value} {scope_id} not found for this tenant")


async def resolve_chain(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    scope: Scope,
    scope_id: uuid.UUID | None,
) -> list[ScopeLink]:
    """Return the chain from ``scope`` up to the tenant, most specific first.

    The tenant link is always last. Raises ``UnknownScopeError`` for a scope
    entity that is not this tenant's.
    """
    await require_scope_entity(session, tenant_id, scope, scope_id)
    if scope is Scope.TENANT:
        return [ScopeLink(Scope.TENANT, None)]

    chain: list[ScopeLink] = [ScopeLink(scope, scope_id)]

    # A user is personal: it inherits straight from the tenant.
    if scope is Scope.USER:
        chain.append(ScopeLink(Scope.TENANT, None))
        return chain

    # A channel override resolves through the warehouse that serves it.
    current_scope = Scope.WAREHOUSE if scope is Scope.CHANNEL else scope
    current_id = scope_id
    if scope is Scope.CHANNEL:
        chain.append(ScopeLink(Scope.WAREHOUSE, current_id))

    while current_scope in _PARENT_COLUMN:
        table, parent_scope, column = _PARENT_COLUMN[current_scope]
        sql = f"SELECT {column} FROM {table} WHERE tenant_id = :tid AND id = :sid"  # noqa: S608
        parent_id = (
            await session.execute(text(sql), {"tid": tenant_id, "sid": current_id})
        ).scalar_one_or_none()
        if parent_id is None:
            # Optional parent (e.g. a warehouse not attached to a branch): skip it.
            if parent_scope is Scope.BRANCH:
                break
            break
        chain.append(ScopeLink(parent_scope, parent_id))
        current_scope, current_id = parent_scope, parent_id

    chain.append(ScopeLink(Scope.TENANT, None))
    return chain
