"""What the backfill reads must land in the inbox, once, and without pretending it is new.

The walk alone left a store that connects today with an empty inbox, and a missed webhook left a
hole nothing filled. These tests pin the three properties the writer owes: a message is stored
once, history never wakes the agent, and Meta's own numbers replace the "now" that
``add_message`` writes for a live message.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.conversations.gateway.messenger_backfill import BackfillResult
from app.modules.conversations.messenger_backfill_service import MessengerBackfillService
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.workers import messenger_backfill_worker as worker

TENANT = uuid.uuid4()
PAGE = "PAGE-1"
PSID = "PSID-9"


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, existing_mids: set[str] | None = None) -> None:
        self.existing = existing_mids or set()

    async def execute(self, stmt):
        # The dedupe query is the only read the writer makes; its bound params carry the mid.
        params = stmt.compile().params
        mid = next((v for v in params.values() if isinstance(v, str) and v.startswith("m_")), None)
        return _Result(uuid.uuid4() if mid in self.existing else None)


def _wire(monkeypatch, *, existing: set[str] | None = None, anchor=None):
    session = _Session(existing)
    sent: list[dict] = []
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        unread_count=7,
        last_customer_message_at=anchor,
    )

    async def get_or_create_customer(session_, tenant_id, *, channel, external_id, name):
        assert external_id == PSID
        return SimpleNamespace(id=uuid.uuid4())

    async def get_or_create_conversation(session_, tenant_id, *, customer_id, channel):
        return conversation

    async def add_message(session_, tenant_id, **kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(CustomerService, "get_or_create_by_identity", get_or_create_customer)
    monkeypatch.setattr(ConversationService, "get_or_create", get_or_create_conversation)
    monkeypatch.setattr(ConversationService, "add_message", add_message)
    return session, sent, conversation


def _walk(messages: list[dict], *, unread: int = 2) -> BackfillResult:
    result = BackfillResult()
    result.conversations.append(
        {
            "id": "t_1",
            "unread_count": unread,
            "participants": {"data": [{"id": PAGE}, {"id": PSID}]},
        }
    )
    result.messages_by_conversation["t_1"] = messages
    result.messages.extend(messages)
    return result


def _message(
    mid: str, *, body: str = "أهلاً", sender: str = PSID, at: str = "2026-11-19T10:00:00+0000"
):
    return {"id": mid, "message": body, "from": {"id": sender}, "created_time": at}


@pytest.mark.asyncio
async def test_a_backfilled_message_is_stored_once_and_silently(monkeypatch):
    session, sent, _ = _wire(monkeypatch)

    summary = await MessengerBackfillService.persist(
        session, TENANT, page_id=PAGE, result=_walk([_message("m_1")])
    )

    assert summary["messages_stored"] == 1
    assert summary["threads"] == 1
    stored = sent[0]
    assert stored["direction"] == "inbound" and stored["sender_type"] == "customer"
    assert stored["channel_message_id"] == "m_1"
    assert stored["provider_metadata"] == {"backfilled": True}
    # No outbox event is written anywhere in this path, so the agent cannot answer history.
    assert "event_type" not in stored


@pytest.mark.asyncio
async def test_the_page_side_of_a_thread_is_outbound(monkeypatch):
    session, sent, _ = _wire(monkeypatch)

    await MessengerBackfillService.persist(
        session, TENANT, page_id=PAGE, result=_walk([_message("m_2", sender=PAGE)])
    )

    assert sent[0]["direction"] == "outbound" and sent[0]["sender_type"] == "agent"


@pytest.mark.asyncio
async def test_a_second_run_duplicates_nothing(monkeypatch):
    session, sent, _ = _wire(monkeypatch, existing={"m_1"})

    summary = await MessengerBackfillService.persist(
        session, TENANT, page_id=PAGE, result=_walk([_message("m_1")])
    )

    assert summary["messages_stored"] == 0
    assert summary["duplicates"] == 1
    assert sent == []


@pytest.mark.asyncio
async def test_history_does_not_arrive_unread_or_reopen_the_window(monkeypatch):
    earlier = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
    session, _, conversation = _wire(monkeypatch, anchor=earlier)

    await MessengerBackfillService.persist(
        session,
        TENANT,
        page_id=PAGE,
        result=_walk([_message("m_1", at="2026-11-19T10:00:00+0000")], unread=2),
    )

    assert conversation.unread_count == 2  # Meta's own count, not add_message's increment
    assert conversation.last_customer_message_at == datetime(2026, 11, 19, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_an_older_message_never_moves_the_window_backwards(monkeypatch):
    recent = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)
    session, _, conversation = _wire(monkeypatch, anchor=recent)

    await MessengerBackfillService.persist(
        session,
        TENANT,
        page_id=PAGE,
        result=_walk([_message("m_1", at="2026-11-19T10:00:00+0000")]),
    )

    assert conversation.last_customer_message_at == recent


@pytest.mark.asyncio
async def test_a_thread_without_an_identifiable_person_is_skipped(monkeypatch):
    session, sent, _ = _wire(monkeypatch)
    result = _walk([_message("m_1")])
    result.conversations[0]["participants"] = {"data": [{"id": PAGE}]}

    summary = await MessengerBackfillService.persist(session, TENANT, page_id=PAGE, result=result)

    assert summary["skipped"] == 1 and sent == []


@pytest.mark.asyncio
async def test_an_attachment_with_no_text_is_counted_not_invented(monkeypatch):
    session, sent, _ = _wire(monkeypatch)

    summary = await MessengerBackfillService.persist(
        session, TENANT, page_id=PAGE, result=_walk([_message("m_1", body="")])
    )

    assert summary["skipped"] == 1 and sent == []


@pytest.mark.asyncio
async def test_the_per_thread_cap_is_respected(monkeypatch):
    session, sent, _ = _wire(monkeypatch)

    await MessengerBackfillService.persist(
        session,
        TENANT,
        page_id=PAGE,
        result=_walk([_message(f"m_{i}") for i in range(5)]),
        max_messages_per_conversation=2,
    )

    assert len(sent) == 2


# ---------------------------------------------------------------- the sweep --


def _integration(**meta) -> SimpleNamespace:
    return SimpleNamespace(config={"_meta": meta} if meta else {})


def test_a_page_never_read_is_due():
    assert worker.is_due(_integration()) is True


def test_a_page_read_recently_is_not_due():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    ran = (now - timedelta(hours=1)).isoformat()
    assert worker.is_due(_integration(backfill={"ran_at": ran}), now) is False


def test_a_page_read_long_ago_is_due_again():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    ran = (now - timedelta(hours=7)).isoformat()
    assert worker.is_due(_integration(backfill={"ran_at": ran}), now) is True


def test_a_failed_read_is_retried_sooner_than_a_healthy_one():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    ran = (now - timedelta(hours=2)).isoformat()
    assert worker.is_due(_integration(backfill={"ran_at": ran}), now) is False
    assert worker.is_due(_integration(backfill={"ran_at": ran, "error": "429"}), now) is True


def test_the_outcome_is_recorded_so_the_next_sweep_knows():
    integration = _integration(page_id=PAGE)
    worker._record(
        integration,
        {"threads": 2, "messages_stored": 9, "duplicates": 1, "skipped": 0, "stopped": "capped"},
    )

    backfill = integration.config["_meta"]["backfill"]
    assert backfill["messages_stored"] == 9 and backfill["stopped"] == "capped"
    assert "error" not in backfill
    assert integration.config["_meta"]["page_id"] == PAGE  # existing facts survive
