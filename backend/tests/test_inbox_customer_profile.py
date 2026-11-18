"""The inbox list shows an Instagram customer's @handle and photo, from the real SQL."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.modules.conversations import inbox as inbox_mod
from app.modules.conversations.inbox import InboxQuery
from app.modules.conversations.models import Conversation
from app.modules.conversations.routers._deps import _redact_inbox_item
from app.modules.customers.models import CustomerIdentity
from app.modules.customers.services.customer import CustomerService


async def _chat(db, t, channel, ext, name, extra=None):
    cust = await CustomerService.get_or_create_by_identity(db, t, channel, ext, name=name)
    await db.flush()
    if extra is not None:
        ident = (
            await db.execute(
                CustomerIdentity.__table__.select().where(
                    CustomerIdentity.tenant_id == t, CustomerIdentity.external_id == ext
                )
            )
        ).first()
        await db.execute(
            CustomerIdentity.__table__.update()
            .where(CustomerIdentity.id == ident.id)
            .values(extra=extra)
        )
    conv = Conversation(tenant_id=t, customer_id=cust.id, channel=channel, status="open")
    db.add(conv)
    await db.flush()
    return conv


@pytest.fixture
def signed(monkeypatch):
    class _S:
        def signed_url(self, key, **_):
            return f"https://signed.example/{key}"

    monkeypatch.setattr("app.core.storage.get_storage", lambda: _S())


async def test_an_instagram_chat_carries_the_handle_and_a_signed_photo_link(
    db, tenant_ctx, signed
) -> None:
    t = tenant_ctx.tenant_id
    await _chat(
        db,
        t,
        "instagram",
        "igsid-1",
        "Sara",
        {"username": "sara.a", "avatar_key": "avatars/k1.png"},
    )
    (item,) = await InboxQuery.page(db, t)
    assert item["customer_handle"] == "sara.a"
    assert item["customer_avatar_url"] == "https://signed.example/avatars/k1.png"


async def test_a_chat_without_a_profile_has_none_rather_than_missing_keys(
    db, tenant_ctx, signed
) -> None:
    t = tenant_ctx.tenant_id
    await _chat(db, t, "instagram", "igsid-2", "1784140000000002")
    (item,) = await InboxQuery.page(db, t)
    assert item["customer_handle"] is None and item["customer_avatar_url"] is None


async def test_other_channels_are_untouched_and_never_duplicated(db, tenant_ctx, signed) -> None:
    t = tenant_ctx.tenant_id
    # One person with BOTH a WhatsApp and an Instagram identity must not double their rows.
    wa = await _chat(db, t, "whatsapp", "2010000001", "Omar")
    cust_id = wa.customer_id
    db.add(
        CustomerIdentity(
            tenant_id=t,
            customer_id=cust_id,
            channel="instagram",
            external_id="igsid-3",
            extra={"username": "omar.ig", "avatar_key": "avatars/o.png"},
        )
    )
    ig = Conversation(tenant_id=t, customer_id=cust_id, channel="instagram", status="open")
    db.add(ig)
    await db.flush()
    items = await InboxQuery.page(db, t)
    assert len(items) == 2
    by_channel = {i["channel"]: i for i in items}
    assert by_channel["instagram"]["customer_handle"] == "omar.ig"
    assert by_channel["whatsapp"]["customer_handle"] is None  # the WhatsApp row never borrows it


async def test_the_page_is_still_one_statement(db, tenant_ctx, signed) -> None:
    t = tenant_ctx.tenant_id
    for i in range(5):
        await _chat(
            db,
            t,
            "instagram",
            f"igsid-n{i}",
            f"c{i}",
            {"username": f"u{i}", "avatar_key": f"a{i}.png"},
        )
    seen: list[str] = []

    def _count(conn, cursor, statement, *a):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    sync = db.sync_session.get_bind()
    event.listen(sync, "before_cursor_execute", _count)
    try:
        items = await InboxQuery.page(db, t, limit=50)
    finally:
        event.remove(sync, "before_cursor_execute", _count)
    assert len(items) == 5 and len(seen) == 1, f"expected 1 statement, got {len(seen)}"


def test_handle_and_photo_are_hidden_without_pii_read() -> None:
    item = {
        "id": "1",
        "customer_name": "Sara",
        "customer_phone": "2010",
        "customer_handle": "sara.a",
        "customer_avatar_url": "https://signed/x",
    }
    seen = _redact_inbox_item(item, permission_codes={"conversations:read"})
    assert seen["customer_handle"] != "sara.a" and seen["customer_avatar_url"] != "https://signed/x"
    assert _redact_inbox_item(item, permission_codes={"pii:read"})["customer_handle"] == "sara.a"


async def test_a_storage_failure_never_breaks_the_list(db, tenant_ctx, monkeypatch) -> None:
    t = tenant_ctx.tenant_id
    await _chat(db, t, "instagram", "igsid-4", "Sara", {"username": "s", "avatar_key": "k"})

    def boom():
        raise RuntimeError("s3 down")

    monkeypatch.setattr("app.core.storage.get_storage", boom)
    (item,) = await InboxQuery.page(db, t)
    assert item["customer_avatar_url"] is None and item["customer_handle"] == "s"


def test_the_helper_is_the_one_the_query_uses() -> None:
    assert inbox_mod._avatar_url(None) is None


async def test_follower_facts_reach_the_list(db, tenant_ctx, signed) -> None:
    t = tenant_ctx.tenant_id
    await _chat(
        db,
        t,
        "instagram",
        "igsid-5",
        "Sara",
        {
            "username": "sara.a",
            "verified": True,
            "follower_count": 12500,
            "follows_you": True,
            "you_follow": False,
        },
    )
    (item,) = await InboxQuery.page(db, t)
    assert item["customer_verified"] is True
    assert item["customer_follower_count"] == 12500
    assert item["customer_follows_you"] is True
    assert item["customer_you_follow"] is False


async def test_a_chat_Instagram_told_us_nothing_about_has_none_not_false(
    db, tenant_ctx, signed
) -> None:
    t = tenant_ctx.tenant_id
    await _chat(db, t, "instagram", "igsid-6", "1784140000000006")
    (item,) = await InboxQuery.page(db, t)
    for key in (
        "customer_verified",
        "customer_follower_count",
        "customer_follows_you",
        "customer_you_follow",
    ):
        assert item[key] is None, key


def test_follower_facts_are_hidden_without_pii_read() -> None:
    item = {
        "id": "1",
        "customer_verified": True,
        "customer_follower_count": 12500,
        "customer_follows_you": True,
        "customer_you_follow": False,
    }
    seen = _redact_inbox_item(item, permission_codes={"conversations:read"})
    for key in ("customer_verified", "customer_follower_count", "customer_follows_you"):
        assert seen[key] != item[key], key
    assert _redact_inbox_item(item, permission_codes={"pii:read"}) == item


@pytest.mark.parametrize(
    ("raw", "flag"),
    [("true", True), ("True", True), ("false", False), ("", False), (None, None)],
)
def test_flag_reads_a_stored_yes_no(raw, flag) -> None:
    assert inbox_mod._flag(raw) is flag


@pytest.mark.parametrize(
    ("raw", "count"),
    [("12500", 12500), ("0", 0), ("-4", None), ("abc", None), ("", None), (None, None)],
)
def test_count_reads_a_stored_number(raw, count) -> None:
    assert inbox_mod._count(raw) == count
