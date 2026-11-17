"""Pin, mute, archive and mark-unread: shared list flags on a conversation.

These are inbox-only. The properties that matter: a flag moves only when asked,
pinned and archived exclude each other (as in WhatsApp), a mute is a bounded
date unless "always", opening a chat clears a manual "unread", the archive is a
filter on the list, and nothing about it reaches the channel provider.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.modules.conversations.inbox import InboxQuery
from app.modules.conversations.routers._deps import ListStateRequest
from app.modules.conversations.routers.inbox import mark_read, set_list_state
from app.modules.conversations.service import ConversationService
from tests._pos_helpers import ctx_for

adapter = WhatsAppAdapter()


async def _chat(db, tenant_id) -> uuid.UUID:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa, "profile": {"name": "Sara"}}],
                            "messages": [
                                {
                                    "from": wa,
                                    "id": f"wamid.{uuid.uuid4().hex}",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "مرحبا"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    (inbound,) = adapter.parse_inbound(payload)
    conversation_id = await IngestService.ingest(
        db, tenant_id=tenant_id, message=inbound, idempotency_scope="webhook:whatsapp"
    )
    assert conversation_id is not None
    return conversation_id


async def _page_ids(db, tenant_id, **kw) -> set[str]:
    rows = await InboxQuery.page(db, tenant_id, limit=200, **kw)
    return {r["id"] for r in rows}


# ---- the request schema ---------------------------------------------------------


def test_mute_only_accepts_the_known_durations() -> None:
    for ok in ("8h", "1w", "always", "off"):
        assert ListStateRequest(mute=ok).mute == ok
    with pytest.raises(PydanticValidationError):
        ListStateRequest(mute="9999-01-01")


def test_an_empty_request_changes_nothing() -> None:
    body = ListStateRequest()
    assert (body.pinned, body.archived, body.marked_unread, body.mute) == (None, None, None, None)


# ---- the rules ------------------------------------------------------------------


async def test_a_new_conversation_has_no_flags(db, tenant_ctx) -> None:
    cid = await _chat(db, tenant_ctx.tenant_id)
    row = next(
        r for r in await InboxQuery.page(db, tenant_ctx.tenant_id, limit=50) if r["id"] == str(cid)
    )
    assert row["pinned_at"] is None
    assert row["muted_until"] is None
    assert row["archived_at"] is None
    assert row["marked_unread"] is False


async def test_pinning_and_archiving_exclude_each_other(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    cid = await _chat(db, tid)

    c = await ConversationService.set_list_state(db, tid, cid, pinned=True)
    assert c.pinned_at is not None and c.archived_at is None

    c = await ConversationService.set_list_state(db, tid, cid, archived=True)
    assert c.archived_at is not None and c.pinned_at is None  # archiving unpins

    c = await ConversationService.set_list_state(db, tid, cid, pinned=True)
    assert c.pinned_at is not None and c.archived_at is None  # pinning restores it


async def test_a_flag_that_is_not_named_does_not_move(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    cid = await _chat(db, tid)
    await ConversationService.set_list_state(db, tid, cid, pinned=True)
    c = await ConversationService.set_list_state(db, tid, cid, marked_unread=True)
    assert c.pinned_at is not None  # untouched
    assert c.marked_unread is True


async def test_the_route_turns_a_duration_into_a_date(db, tenant_ctx) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx.tenant_id)

    before = datetime.now(UTC)
    out = await set_list_state(cid, ListStateRequest(mute="8h"), ctx=ctx)
    muted = datetime.fromisoformat(out["muted_until"])
    assert before + timedelta(hours=7, minutes=59) < muted < before + timedelta(hours=8, minutes=1)

    out = await set_list_state(cid, ListStateRequest(mute="always"), ctx=ctx)
    assert datetime.fromisoformat(out["muted_until"]).year == 9999

    out = await set_list_state(cid, ListStateRequest(mute="off"), ctx=ctx)
    assert out["muted_until"] is None


async def test_the_route_leaves_a_mute_alone_when_none_is_sent(db, tenant_ctx) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx.tenant_id)
    await set_list_state(cid, ListStateRequest(mute="1w"), ctx=ctx)
    out = await set_list_state(cid, ListStateRequest(pinned=True), ctx=ctx)
    assert out["muted_until"] is not None
    assert out["pinned_at"] is not None


async def test_opening_a_chat_clears_a_manual_unread(db, tenant_ctx) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx.tenant_id)
    await set_list_state(cid, ListStateRequest(marked_unread=True), ctx=ctx)
    await mark_read(ctx, cid)
    row = next(
        r for r in await InboxQuery.page(db, tenant_ctx.tenant_id, limit=50) if r["id"] == str(cid)
    )
    assert row["marked_unread"] is False
    assert row["unread_count"] == 0


# ---- the list -------------------------------------------------------------------


async def test_the_default_list_hides_archived_and_the_archive_view_shows_only_them(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    kept = await _chat(db, tid)
    gone = await _chat(db, tid)
    await ConversationService.set_list_state(db, tid, gone, archived=True)

    inbox = await _page_ids(db, tid)  # archived defaults to False
    assert str(kept) in inbox and str(gone) not in inbox

    archive = await _page_ids(db, tid, archived=True)
    assert str(gone) in archive and str(kept) not in archive

    everything = await _page_ids(db, tid, archived=None)
    assert {str(kept), str(gone)} <= everything


async def test_pinned_only_returns_the_pinned_strip(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    pinned = await _chat(db, tid)
    plain = await _chat(db, tid)
    await ConversationService.set_list_state(db, tid, pinned, pinned=True)
    ids = await _page_ids(db, tid, pinned_only=True)
    assert str(pinned) in ids and str(plain) not in ids


async def test_an_unknown_conversation_is_not_found(db, tenant_ctx) -> None:
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await ConversationService.set_list_state(
            db, tenant_ctx.tenant_id, uuid.uuid4(), pinned=True
        )
