"""Instagram customer profiles: what is learned, what is protected, what never blocks a message."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import ExternalProviderError
from app.core.storage import FetchedMedia, StoredMedia
from app.modules.conversations import customer_profile as cp
from app.modules.conversations.customer_profile import (
    CustomerProfileService,
    looks_like_an_id,
    needs_refresh,
)
from app.modules.customers.models import CustomerIdentity
from app.modules.customers.services.customer import CustomerService

CREDS = {"api_key": "t", "account_id": "ig1"}
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeIG:
    def __init__(self, profile=None, error: Exception | None = None):
        self.profile, self.error, self.calls = profile, error, 0

    async def get_user_profile(self, creds, igsid):
        self.calls += 1
        if self.error:
            raise self.error
        return self.profile


class FakeStorage:
    def __init__(self, content_type="image/png", fail=False, durable=True):
        self.content_type, self.fail, self.durable, self.stored = content_type, fail, durable, []

    async def fetch(self, url, *, max_bytes=None):
        if self.fail:
            raise RuntimeError("cdn down")
        return FetchedMedia(data=PNG, content_type=self.content_type, checksum="0" * 64)

    async def store(self, media, *, prefix="media", original_url=None):
        self.stored.append(prefix)
        return StoredMedia(
            url="https://ours/a",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=self.durable,
            storage_key="avatars/k1.png",
        )


PROFILE = {
    "name": "Sara Ahmed",
    "username": "sara.a",
    "profile_pic": "https://cdn/p.png",
    "verified": False,
    "follower_count": 120,
    "follows_you": True,
    "you_follow": False,
}


async def _customer(db, tenant_id, name="1784140000000001"):
    c = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "instagram", "igsid-1", name=name
    )
    await db.flush()
    return c


async def _identity(db, tenant_id) -> CustomerIdentity:
    return (
        await db.execute(
            select(CustomerIdentity).where(
                CustomerIdentity.tenant_id == tenant_id, CustomerIdentity.channel == "instagram"
            )
        )
    ).scalar_one()


def test_a_number_is_not_a_name():
    assert looks_like_an_id(None) and looks_like_an_id("  ") and looks_like_an_id("17841400000000")
    assert (
        not looks_like_an_id("Sara")
        and not looks_like_an_id("سارة")
        and not looks_like_an_id("Shop 24")
    )


def test_refresh_timing():
    assert needs_refresh(None, T0) and needs_refresh({}, T0)
    ok = {"profile_ok": True, "profile_at": (T0 - timedelta(days=6)).isoformat()}
    assert not needs_refresh(ok, T0) and needs_refresh(
        {**ok, "profile_at": (T0 - timedelta(days=8)).isoformat()}, T0
    )
    refused = {"profile_ok": False, "profile_at": (T0 - timedelta(hours=5)).isoformat()}
    assert not needs_refresh(refused, T0)
    assert needs_refresh({**refused, "profile_at": (T0 - timedelta(hours=7)).isoformat()}, T0)
    assert needs_refresh({"profile_at": "garbage"}, T0)


async def test_learns_the_profile_and_copies_the_photo(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG(PROFILE))
    c, st = await _customer(db, t), FakeStorage()
    assert (
        await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0, storage=st) is True
    )
    ex = (await _identity(db, t)).extra
    assert (ex["username"], ex["follower_count"], ex["follows_you"], ex["you_follow"]) == (
        "sara.a",
        120,
        True,
        False,
    )
    assert (
        ex["avatar_key"] == "avatars/k1.png" and "profile_pic" not in ex
    )  # our copy, never the expiring link
    assert st.stored == ["avatars"] and c.name == "Sara Ahmed"


async def test_a_name_the_merchant_typed_is_never_replaced(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG(PROFILE))
    c = await _customer(db, t, name="Sara (VIP)")
    await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0, storage=FakeStorage())
    assert c.name == "Sara (VIP)"


async def test_no_real_name_falls_back_to_the_handle(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG({**PROFILE, "name": None}))
    c = await _customer(db, t)
    await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0, storage=FakeStorage())
    assert c.name == "sara.a"


async def test_a_refusal_is_remembered_and_not_retried_on_every_message(
    db, tenant_ctx, monkeypatch
) -> None:
    t = tenant_ctx.tenant_id
    ig = FakeIG(None)
    monkeypatch.setattr(cp, "instagram_adapter", ig)
    c = await _customer(db, t)
    assert await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0) is False
    assert (await _identity(db, t)).extra["profile_ok"] is False
    await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0 + timedelta(hours=1))
    assert ig.calls == 1 and c.name == "1784140000000001"
    await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0 + timedelta(hours=7))
    assert ig.calls == 2


async def test_a_fresh_profile_is_not_fetched_again(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    ig = FakeIG(PROFILE)
    monkeypatch.setattr(cp, "instagram_adapter", ig)
    c = await _customer(db, t)
    await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0, storage=FakeStorage())
    await CustomerProfileService.enrich_instagram(
        db, t, c, CREDS, now=T0 + timedelta(days=3), storage=FakeStorage()
    )
    assert ig.calls == 1


async def test_an_outage_never_raises_and_changes_nothing(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG(error=ExternalProviderError("boom")))
    c = await _customer(db, t)
    assert await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0) is False
    assert c.name == "1784140000000001"


@pytest.mark.parametrize("ctype", ["image/svg+xml", "image/gif", "text/html", "application/pdf"])
async def test_only_safe_photo_types_are_kept(db, tenant_ctx, monkeypatch, ctype) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG(PROFILE))
    c, st = await _customer(db, t), FakeStorage(content_type=ctype)
    await CustomerProfileService.enrich_instagram(db, t, c, CREDS, now=T0, storage=st)
    ex = (await _identity(db, t)).extra
    assert "avatar_key" not in ex and st.stored == []
    assert ex["username"] == "sara.a"  # the rest of the profile is still learned


async def test_a_photo_failure_keeps_the_rest_of_the_profile(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG(PROFILE))
    c = await _customer(db, t)
    assert (
        await CustomerProfileService.enrich_instagram(
            db, t, c, CREDS, now=T0, storage=FakeStorage(fail=True)
        )
        is True
    )
    ex = (await _identity(db, t)).extra
    assert "avatar_key" not in ex and ex["username"] == "sara.a" and c.name == "Sara Ahmed"


async def test_a_pass_through_photo_is_not_kept_because_its_link_expires(
    db, tenant_ctx, monkeypatch
) -> None:
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(cp, "instagram_adapter", FakeIG(PROFILE))
    c = await _customer(db, t)
    await CustomerProfileService.enrich_instagram(
        db, t, c, CREDS, now=T0, storage=FakeStorage(durable=False)
    )
    assert "avatar_key" not in (await _identity(db, t)).extra
