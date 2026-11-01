"""Per-user channel access and the single server-side channel-status predicate.

Connection is tenant-wide; access is per user. A missing grant means the
tenant default (enabled), so shipping this table does not lock anyone out.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.channel_specs.registry import list_connection_specs
from app.modules.platform.models import ChannelUserAccess, Integration
from app.modules.platform.services.audit import AuditService

_ALL_ACCESS_ROLES = frozenset({"owner", "manager"})
_SIGNED_WEBHOOK_PROVIDERS = frozenset(
    {"whatsapp", "facebook", "messenger", "instagram", "telegram"}
)


def _verified_at(integration: Integration) -> str | None:
    connection = (integration.config or {}).get("_connection") or {}
    value = connection.get("verified_at")
    return str(value) if value else None


def _display_name(integration: Integration | None) -> str | None:
    if integration is None:
        return None
    connection = (integration.config or {}).get("_connection") or {}
    value = connection.get("display_name")
    return str(value) if value else None


def _webhook_status(integration: Integration) -> str:
    provider = integration.provider
    if provider == "webchat":
        return "ready" if integration.status in ("active", "connected") else "not_connected"
    if provider == "telegram":
        connection = (integration.config or {}).get("_connection") or {}
        if integration.status not in ("active", "connected"):
            return "not_connected"
        return "ready" if connection.get("webhook_configured_at") else "server_setup_required"
    if provider in _SIGNED_WEBHOOK_PROVIDERS:
        health = integration.webhook_health or {}
        if health.get("last_webhook_at"):
            return "receiving"
        if integration.status in ("active", "connected"):
            return "awaiting_first_event"
    return "not_connected"


def _connected(integration: Integration | None) -> bool:
    if integration is None:
        return False
    return integration.status in ("active", "connected") and _verified_at(integration) is not None


async def access_rows(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, ChannelUserAccess]:
    rows = (
        await session.execute(
            select(ChannelUserAccess).where(
                ChannelUserAccess.tenant_id == tenant_id,
                ChannelUserAccess.user_id == user_id,
            )
        )
    ).scalars()
    return {row.provider: row for row in rows}


async def allowed_providers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_code: str | None,
) -> set[str] | None:
    """Providers this user may see. None means every provider (owner/manager)."""
    if (role_code or "").lower() in _ALL_ACCESS_ROLES:
        return None
    rows = await access_rows(session, tenant_id, user_id)
    return {provider for provider, row in rows.items() if row.is_enabled} | {
        spec.name for spec in list_connection_specs() if spec.name not in rows
    }


async def channel_status(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_code: str | None,
) -> list[dict]:
    """One row per known channel: connection truth + this user's access."""
    integrations = (
        (
            await session.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_id,
                    Integration.kind == "channel",
                )
            )
        )
        .scalars()
        .all()
    )
    by_provider = {row.provider: row for row in integrations}
    rows = await access_rows(session, tenant_id, user_id)
    all_allowed = (role_code or "").lower() in _ALL_ACCESS_ROLES

    result: list[dict] = []
    for spec in list_connection_specs():
        integration = by_provider.get(spec.name)
        access = rows.get(spec.name)
        enabled_for_me = (
            True if all_allowed else (access.is_enabled if access is not None else True)
        )
        connected = _connected(integration)
        result.append(
            {
                "provider": spec.name,
                "display_name": spec.display_name,
                "connected": connected,
                "enabled_for_me": enabled_for_me,
                "can_send": True
                if all_allowed
                else (access.can_send if access is not None else True),
                "locked": not connected or not enabled_for_me,
                "lifecycle": integration.status if integration else "not_connected",
                "credentials_verified": (
                    _verified_at(integration) is not None if integration else False
                ),
                "webhook_status": _webhook_status(integration) if integration else "not_connected",
                "account_name": _display_name(integration),
                "last_webhook_at": (
                    (integration.webhook_health or {}).get("last_webhook_at")
                    if integration
                    else None
                ),
            }
        )
    return result


async def set_access(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: str,
    *,
    enabled: bool,
    can_send: bool = True,
    actor_user_id: uuid.UUID | None = None,
) -> ChannelUserAccess:
    provider = provider.strip().lower()
    known = {spec.name for spec in list_connection_specs()}
    if provider not in known:
        raise ValueError(f"unknown channel provider: {provider}")

    row = (
        await session.execute(
            select(ChannelUserAccess).where(
                ChannelUserAccess.tenant_id == tenant_id,
                ChannelUserAccess.user_id == user_id,
                ChannelUserAccess.provider == provider,
            )
        )
    ).scalar_one_or_none()
    before = None if row is None else {"is_enabled": row.is_enabled, "can_send": row.can_send}
    if row is None:
        row = ChannelUserAccess(
            tenant_id=tenant_id,
            user_id=user_id,
            provider=provider,
            is_enabled=enabled,
            can_send=can_send,
            granted_by=actor_user_id,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            row = (
                await session.execute(
                    select(ChannelUserAccess).where(
                        ChannelUserAccess.tenant_id == tenant_id,
                        ChannelUserAccess.user_id == user_id,
                        ChannelUserAccess.provider == provider,
                    )
                )
            ).scalar_one()
            row.is_enabled = enabled
            row.can_send = can_send
            row.granted_by = actor_user_id
    else:
        row.is_enabled = enabled
        row.can_send = can_send
        row.granted_by = actor_user_id
    await session.flush()

    await AuditService.write(
        session,
        tenant_id,
        actor_user_id,
        "channel.access.updated",
        "channel_user_access",
        str(row.id),
        before=before,
        after={"is_enabled": enabled, "can_send": can_send, "provider": provider},
    )
    return row
