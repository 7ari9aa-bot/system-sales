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

A ``channel`` is a row: the tenant's ``integrations`` row for that provider. Its
``scope_id`` is that integration id, so two channels served by the same warehouse keep
separate overrides. (It used to be a warehouse id, which made a WhatsApp setting and an
Instagram setting on one warehouse the same row.) A channel resolves up through the
warehouse named in its ``config->>'warehouse_id'`` when there is one, then branch,
workspace, tenant.

All reads here go through the tenant-bound session, so RLS applies a second time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import NotFoundError
from app.modules.settings.registry import Scope

# integrations.kind value a channel scope must carry.
_CHANNEL_KIND = "channel"


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
    Scope.BRANCH: ("locations", Scope.WORKSPACE, "workspace_id"),
}

# Tables whose primary key IS the scope id, for scopes with no parent column.
_ROOT_TABLE: dict[Scope, str] = {
    Scope.WORKSPACE: "workspaces",
    Scope.BRANCH: "locations",
    Scope.WAREHOUSE: "warehouses",
    Scope.POS_PROFILE: "pos_profiles",
    Scope.REGISTER: "pos_registers",
    Scope.USER: "tenant_users",
    # A channel's identity is its integration row, not the warehouse behind it.
    Scope.CHANNEL: "integrations",
}


async def _channel_kind(
    session: AsyncSession, tenant_id: uuid.UUID, channel_id: uuid.UUID
) -> str | None:
    """The ``kind`` of an integration row, or None when it is not this tenant's."""
    sql = "SELECT kind FROM integrations WHERE tenant_id = :tid AND id = :sid"  # noqa: S608
    return (
        await session.execute(text(sql), {"tid": tenant_id, "sid": channel_id})
    ).scalar_one_or_none()


async def _exists(session: AsyncSession, scope: Scope, scope_id: uuid.UUID, tenant_id) -> bool:
    table = _ROOT_TABLE.get(scope)
    if table is None:
        return False
    if scope is Scope.CHANNEL:
        # A channel scope is a *channel* account. Any other integration row — an oauth
        # grant, an api_key — is not a channel, and accepting its id would create a
        # settings chain hanging off something that never receives messages.
        return await _channel_kind(session, tenant_id, scope_id) == _CHANNEL_KIND
    if scope is Scope.USER:
        sql = f"SELECT 1 FROM {table} WHERE tenant_id = :tid AND user_id = :sid"  # noqa: S608
    else:
        sql = f"SELECT 1 FROM {table} WHERE tenant_id = :tid AND id = :sid"  # noqa: S608
    row = await session.execute(text(sql), {"tid": tenant_id, "sid": scope_id})
    return row.first() is not None


async def _channel_warehouse(
    session: AsyncSession, tenant_id: uuid.UUID, channel_id: uuid.UUID
) -> uuid.UUID | None:
    """The warehouse a channel integration names, or None when it serves all of them."""
    sql = (
        "SELECT NULLIF(config->>'warehouse_id', '')::uuid FROM integrations "  # noqa: S608
        "WHERE tenant_id = :tid AND id = :sid"
    )
    return (
        await session.execute(text(sql), {"tid": tenant_id, "sid": channel_id})
    ).scalar_one_or_none()


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
    if not await _exists(session, scope, scope_id, tenant_id):
        if scope is Scope.CHANNEL:
            kind = await _channel_kind(session, tenant_id, scope_id)
            if kind is not None:
                # It exists but it is not a channel: say so instead of "not found".
                raise UnknownScopeError(
                    f"integration {scope_id} is a {kind!r} integration, not a channel"
                )
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

    # A channel resolves through the warehouse its integration names, when it names one.
    current_scope = scope
    current_id = scope_id
    if scope is Scope.CHANNEL:
        warehouse_id = await _channel_warehouse(session, tenant_id, scope_id)
        if warehouse_id is None:
            chain.append(ScopeLink(Scope.TENANT, None))
            return chain
        current_scope, current_id = Scope.WAREHOUSE, warehouse_id
        chain.append(ScopeLink(Scope.WAREHOUSE, warehouse_id))

    while current_scope in _PARENT_COLUMN:
        table, parent_scope, column = _PARENT_COLUMN[current_scope]
        sql = f"SELECT {column} FROM {table} WHERE tenant_id = :tid AND id = :sid"  # noqa: S608
        parent_id = (
            await session.execute(text(sql), {"tid": tenant_id, "sid": current_id})
        ).scalar_one_or_none()
        if parent_id is None:
            # Optional parent (a warehouse not attached to a branch): the chain ends here and
            # falls straight to the tenant, exactly as it did before workspaces were a scope.
            break
        chain.append(ScopeLink(parent_scope, parent_id))
        current_scope, current_id = parent_scope, parent_id

    chain.append(ScopeLink(Scope.TENANT, None))
    return chain
