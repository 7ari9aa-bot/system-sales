"""What the inbox is told about the WhatsApp Business app link — and where a message came from.

Two screens read this: the strip at the top of a thread (is the number connected, how far did the
history get) and the bubble footer (was this outbound message written by the AI, by a person here,
or on the merchant's own phone). Both are computed, not stored guesses: the sync state is folded
from the run rows on every read, and the origin is the one the import path stamped on the message.

Pure by design — no database, no Meta — so the rules run in every CI job.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.conversations import whatsapp_sync as sync
from app.modules.conversations.models import WhatsAppSyncRun
from app.modules.conversations.routers.inbox import _message_source, _present_messages

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _run(**overrides) -> WhatsAppSyncRun:
    fields = {
        "id": uuid.uuid4(),
        "phone_number_id": "456",
        "sync_type": "history",
        "onboarding_epoch": "2026-11-24T00:00:00+00:00",
        "state": "pending",
    }
    fields.update(overrides)
    return WhatsAppSyncRun(**fields)


# ── the sync snapshot ────────────────────────────────────────────────────────────────────────────


def test_every_state_has_a_sentence_in_both_languages() -> None:
    """A state with no copy would render as an empty strip, which reads as "nothing to say"."""
    states = {
        sync.STATE_ONBOARDING,
        sync.STATE_CONNECTED_PENDING_SYNC,
        sync.STATE_CONTACTS_SYNC_PENDING,
        sync.STATE_CONTACTS_SYNC_IN_PROGRESS,
        sync.STATE_CONTACTS_SYNC_COMPLETED,
        sync.STATE_HISTORY_SYNC_PENDING,
        sync.STATE_HISTORY_SYNC_IN_PROGRESS,
        sync.STATE_HISTORY_SYNC_COMPLETED,
        sync.STATE_HISTORY_NOT_SHARED,
        sync.STATE_READY,
        sync.STATE_SYNC_FAILED,
        sync.STATE_OFFBOARDED,
    }
    assert states == set(sync.STATE_COPY)
    for state, copy in sync.STATE_COPY.items():
        assert copy.get("en"), state
        assert copy.get("ar"), state


def test_run_snapshot_carries_a_bar_and_a_count_but_never_the_request_id() -> None:
    run = _run(
        state="in_progress",
        progress=42,
        messages_stored=128,
        chunks_seen=3,
        request_id="req-secret-handle",
        requested_at=NOW - timedelta(minutes=5),
        deadline_at=NOW + timedelta(hours=23),
        error="131060: unsupported message",
    )
    snapshot = sync.run_snapshot(run)
    assert snapshot["state"] == "in_progress"
    assert snapshot["progress"] == 42
    assert snapshot["messages_stored"] == 128
    assert snapshot["chunks"] == 3
    assert snapshot["requested_at"] and snapshot["deadline_at"]
    # Meta's transfer handle is bookkeeping, not something a screen needs.
    assert "req-secret-handle" not in str(snapshot)
    assert "request_id" not in snapshot


def test_run_snapshot_of_nothing_is_none_not_an_empty_bar() -> None:
    assert sync.run_snapshot(None) is None


def test_ready_is_the_only_state_that_claims_everything_arrived() -> None:
    """Contacts done + history done is READY; anything else must not read as finished."""
    contacts = _run(sync_type="contacts", state="completed")
    history = _run(sync_type="history", state="completed")
    assert sync.channel_sync_state(contacts, history) == sync.STATE_READY

    # A refusal is settled too, but the state still says so instead of pretending READY.
    refused = _run(sync_type="history", state="not_shared")
    state = sync.channel_sync_state(contacts, refused)
    assert state == sync.STATE_HISTORY_NOT_SHARED
    assert sync.is_ready(state)


def test_an_offboarded_channel_says_so_before_anything_else() -> None:
    """PARTNER_REMOVED outranks a finished sync: a synced dead channel is still dead."""
    contacts = _run(sync_type="contacts", state="completed")
    history = _run(sync_type="history", state="completed")
    assert sync.channel_sync_state(contacts, history, offboarded=True) == sync.STATE_OFFBOARDED


# ── where an outbound message came from ─────────────────────────────────────────────────────────


class _Msg:
    """The columns `_present_messages` reads, and nothing else."""

    def __init__(self, *, metadata=None, direction="outbound", sender_type="agent", **extra):
        self.id = uuid.uuid4()
        self.direction = direction
        self.sender_type = sender_type
        self.body = extra.get("body", "hello")
        self.media_url = None
        self.media_type = None
        self.content_type = extra.get("content_type", "text")
        self.status = "sent"
        self.edited = False
        self.deleted = False
        self.created_at = NOW
        self.reply_to_message_id = None
        self.provider_metadata = metadata if metadata is not None else {}
        self.payload = {}


def test_an_echo_keeps_its_business_app_origin_in_the_payload() -> None:
    """The phone's reply must reach the bubble labelled, not as an anonymous outbound line."""
    row = _Msg(metadata={"imported_from": "whatsapp_business_app"})
    assert _message_source(row) == "whatsapp_business_app"
    item = _present_messages([row], {})[0]
    assert item["source"] == "whatsapp_business_app"
    assert item["sender_type"] == "agent"


def test_imported_history_is_marked_as_history() -> None:
    row = _Msg(
        metadata={"imported_from": "whatsapp_history"}, direction="inbound", sender_type="customer"
    )
    assert _present_messages([row], {})[0]["source"] == "whatsapp_history"


def test_a_live_message_has_no_source_and_an_odd_value_is_not_forwarded() -> None:
    assert _message_source(_Msg()) is None
    assert _present_messages([_Msg()], {})[0]["source"] is None
    # A malformed stamp must not reach the UI as an object or a number.
    assert _message_source(_Msg(metadata={"imported_from": {"nope": 1}})) is None
    assert _message_source(_Msg(metadata={"imported_from": "  "})) is None


def test_the_status_route_is_published_and_typed() -> None:
    """The inbox reads this path; it must exist and carry a response model (lock gate)."""
    from app.main import create_app

    schema = create_app().openapi()
    path = "/api/v1/integrations/whatsapp/coexistence-status"
    assert path in schema["paths"], sorted(p for p in schema["paths"] if "whatsapp" in p)
    operation = schema["paths"][path]["get"]
    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok.get("$ref", "").endswith("WhatsAppCoexistenceStatusOut")
