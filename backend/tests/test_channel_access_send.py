"""Per-user channel access grants — the send/see split (deep self-review).

``allowed_providers`` answers "what can this member SEE" (is_enabled only);
``sendable_providers`` answers "what can this member SEND on" (is_enabled AND
can_send). The owner console can make a member view-only; before the send
route enforced the second grant, the advertised control was inert.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.modules.conversations.routers.inbox import _ensure_channel_send
from app.modules.platform.models import ChannelUserAccess
from app.modules.platform.services.channel_access import (
    allowed_providers,
    sendable_providers,
)


async def _grant(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, *, can_send: bool
) -> None:
    db.add(
        ChannelUserAccess(
            tenant_id=tenant_id,
            user_id=user_id,
            provider="whatsapp",
            is_enabled=True,
            can_send=can_send,
        )
    )
    await db.flush()


async def test_view_only_member_can_see_but_not_send(db, tenant_ctx) -> None:
    """can_send=False keeps the channel VISIBLE (the member reads the inbox)
    while the send route refuses it — the two grants are independent."""
    tenant_id = tenant_ctx.tenant_id
    member = tenant_ctx.user.id
    await _grant(db, tenant_id, member, can_send=False)

    visible = await allowed_providers(db, tenant_id, member, "staff")
    sendable = await sendable_providers(db, tenant_id, member, "staff")

    assert visible is not None and "whatsapp" in visible
    assert sendable is not None and "whatsapp" not in sendable


async def test_can_send_true_grant_is_sendable(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    member = tenant_ctx.user.id
    await _grant(db, tenant_id, member, can_send=True)

    sendable = await sendable_providers(db, tenant_id, member, "staff")
    assert sendable is not None and "whatsapp" in sendable


async def test_owner_role_sends_everywhere_without_rows(db, tenant_ctx) -> None:
    sendable = await sendable_providers(db, tenant_ctx.tenant_id, uuid.uuid4(), "owner")
    assert sendable is None, "an owner needs no per-channel rows to send"


async def test_send_route_enforcement_refuses_a_view_only_member(db, tenant_ctx) -> None:
    """The route-level guard itself: _ensure_channel_send raises for a channel
    the member may read but not send on (deep self-review HIGH)."""
    from types import SimpleNamespace

    tenant_id = tenant_ctx.tenant_id
    member = tenant_ctx.user.id
    await _grant(db, tenant_id, member, can_send=False)

    class _Conv:
        channel = "whatsapp"

    # The route passes the authed ctx — role_code rides on the ctx there.
    ctx = SimpleNamespace(
        session=db,
        tenant_id=tenant_id,
        role_code="staff",
        user=SimpleNamespace(id=member),
    )
    with pytest.raises(PermissionDeniedError):
        await _ensure_channel_send(ctx, _Conv())
