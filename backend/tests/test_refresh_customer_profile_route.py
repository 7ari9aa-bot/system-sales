"""POST /conversations/{id}/refresh-profile: learn who an Instagram customer is, on demand."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.modules.conversations.models import Conversation
from app.modules.conversations.routers import inbox as route_mod
from app.modules.conversations.routers.inbox import refresh_customer_profile
from app.modules.customers.models import CustomerIdentity
from app.modules.customers.services.customer import CustomerService
from tests._pos_helpers import ctx_for

PROFILE = {
    "name": "Sara Ahmed",
    "username": "sara.a",
    "profile_pic": None,
    "verified": False,
    "follower_count": 9,
    "follows_you": True,
    "you_follow": False,
}


class _IG:
    def __init__(self):
        self.calls = []

    async def get_user_profile(self, creds, igsid):
        self.calls.append(igsid)
        return PROFILE


@pytest.fixture
def ig(monkeypatch):
    from app.modules.conversations import customer_profile as cp

    fake = _IG()
    monkeypatch.setattr(cp, "instagram_adapter", fake)
    return fake


@pytest.fixture
def connected(monkeypatch):
    async def creds(session, tenant_id, provider):
        return {"api_key": "tok", "account_id": "ig1"}

    monkeypatch.setattr(route_mod._channel_access, "channel_credentials_config", creds)


async def _chat(db, tenant_ctx, channel="instagram", name="1784140000000001"):
    t = tenant_ctx.tenant_id
    cust = await CustomerService.get_or_create_by_identity(db, t, channel, "igsid-1", name=name)
    conv = Conversation(tenant_id=t, customer_id=cust.id, channel=channel, status="open")
    db.add(conv)
    await db.flush()
    return conv.id, cust


async def test_it_names_a_chat_that_was_only_a_number(db, tenant_ctx, ig, connected) -> None:
    cid, cust = await _chat(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    assert await refresh_customer_profile(cid, ctx=ctx) == {"updated": True}
    assert cust.name == "Sara Ahmed" and ig.calls == ["igsid-1"]
    ident = (
        await db.execute(select(CustomerIdentity).where(CustomerIdentity.customer_id == cust.id))
    ).scalar_one()
    assert ident.extra["username"] == "sara.a"


async def test_calling_it_again_does_not_hit_instagram_again(db, tenant_ctx, ig, connected) -> None:
    cid, _ = await _chat(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    await refresh_customer_profile(cid, ctx=ctx)
    assert await refresh_customer_profile(cid, ctx=ctx) == {"updated": False}
    assert len(ig.calls) == 1


async def test_a_whatsapp_chat_is_left_alone(db, tenant_ctx, ig, connected) -> None:
    cid, _ = await _chat(db, tenant_ctx, channel="whatsapp")
    ctx = await ctx_for(db, tenant_ctx, "owner")
    assert await refresh_customer_profile(cid, ctx=ctx) == {
        "updated": False,
        "reason": "not_supported_channel",
    }
    assert ig.calls == []


async def test_a_store_that_is_not_connected_makes_no_call(db, tenant_ctx, ig, monkeypatch) -> None:
    async def none(*a, **k):
        return None

    monkeypatch.setattr(route_mod._channel_access, "channel_credentials_config", none)
    cid, _ = await _chat(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    assert await refresh_customer_profile(cid, ctx=ctx) == {
        "updated": False,
        "reason": "not_connected",
    }
    assert ig.calls == []


async def test_an_unknown_chat_is_not_found(db, tenant_ctx, ig, connected) -> None:
    import uuid

    ctx = await ctx_for(db, tenant_ctx, "owner")
    with pytest.raises(NotFoundError):
        await refresh_customer_profile(uuid.uuid4(), ctx=ctx)


def test_the_route_is_gated_on_conversations_read() -> None:
    r = next(
        x for x in route_mod.router.routes if getattr(x, "path", "").endswith("/refresh-profile")
    )
    assert "POST" in r.methods
    gates = [d.call for d in r.dependant.dependencies if hasattr(d.call, "code")]
    assert [g.code for g in gates] == ["conversations:read"]


async def test_that_gate_refuses_a_user_without_the_permission(db, tenant_ctx) -> None:
    from app.core.errors import PermissionDeniedError
    from app.modules.identity.deps import require_permission

    ctx = await ctx_for(db, tenant_ctx, "owner")
    ctx.permission_codes = set()
    with pytest.raises(PermissionDeniedError):
        await require_permission("conversations:read")(ctx)
