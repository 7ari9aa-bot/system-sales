"""Staff replies from Meta's inbox, and thread handovers, reach our own state.

Meta echoes every message the Page sends. The parser existed but nothing called it, so a
reply typed in Meta Business Suite never appeared in FIHRIST and the agent answered the
same customer again. Thread control had the same fate: a human could take a thread in
Meta and our agent kept replying.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.ai import handover as handover_mod
from app.applications.apparel.modules.conversations.gateway.ingest import IngestService
from app.applications.apparel.modules.conversations.service import ConversationService
from app.applications.apparel.modules.customers.service import CustomerService

TENANT = uuid.uuid4()
OWN_APP = "111222333"


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    """Just enough session: the duplicate check and any write is recorded, not executed."""

    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.queries = 0

    async def execute(self, stmt):
        self.queries += 1
        return _Result(self.existing)


def _wire(monkeypatch, *, existing=None, conversation=True):
    sent: list[dict] = []
    session = _Session(existing)

    async def find_by_identity(session_, tenant_id, channel, external_id):
        return SimpleNamespace(id=uuid.uuid4()) if external_id == "psid-1" else None

    async def open_conversation(session_, tenant_id, channel, customer_id):
        return SimpleNamespace(id=uuid.uuid4(), status="open") if conversation else None

    async def add_message(session_, tenant_id, **kwargs):
        sent.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(CustomerService, "find_by_identity", find_by_identity)
    monkeypatch.setattr(IngestService, "_open_conversation", open_conversation)
    monkeypatch.setattr(ConversationService, "add_message", add_message)
    return session, sent


def _echo(app_id: str | None = OWN_APP, mid: str = "m-1") -> dict:
    return {"customer_ref": "psid-1", "mid": mid, "app_id": app_id, "text": "أهلاً", "timestamp": 1}


@pytest.mark.asyncio
async def test_an_echo_of_our_own_message_is_not_stored_twice(monkeypatch) -> None:
    session, sent = _wire(monkeypatch)

    stored = await IngestService.apply_echoes(
        session, TENANT, "messenger", [_echo()], own_app_id=OWN_APP
    )

    assert stored == 0
    assert sent == []


@pytest.mark.asyncio
async def test_a_reply_sent_from_metas_inbox_is_stored_as_outbound(monkeypatch) -> None:
    session, sent = _wire(monkeypatch)

    stored = await IngestService.apply_echoes(
        session, TENANT, "messenger", [_echo(app_id="999888777")], own_app_id=OWN_APP
    )

    assert stored == 1
    assert sent[0]["direction"] == "outbound"
    assert sent[0]["body"] == "أهلاً"
    assert sent[0]["channel_message_id"] == "m-1"
    assert sent[0]["payload"]["source"] == "meta_echo"


@pytest.mark.asyncio
async def test_a_redelivered_echo_is_skipped(monkeypatch) -> None:
    session, sent = _wire(monkeypatch, existing=uuid.uuid4())

    stored = await IngestService.apply_echoes(
        session, TENANT, "messenger", [_echo(app_id="999")], own_app_id=OWN_APP
    )

    assert stored == 0
    assert sent == []


@pytest.mark.asyncio
async def test_an_echo_from_an_unknown_customer_is_dropped(monkeypatch) -> None:
    session, sent = _wire(monkeypatch)

    stored = await IngestService.apply_echoes(
        session,
        TENANT,
        "messenger",
        [{**_echo(app_id="9"), "customer_ref": "nobody"}],
        own_app_id=OWN_APP,
    )

    assert stored == 0
    assert sent == []


@pytest.mark.asyncio
async def test_take_thread_control_opens_a_handover_and_stops_the_agent(monkeypatch) -> None:
    session, _ = _wire(monkeypatch)
    calls: list[dict] = []

    async def takeover(session_, tenant_id, **kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(handover_mod, "request_human_takeover", takeover)

    applied = await IngestService.apply_handover(
        session, TENANT, "messenger", {"customer_ref": "psid-1", "event": "take_thread_control"}
    )

    assert applied is True
    assert calls[0]["reason"] == "meta_thread_control"


@pytest.mark.asyncio
async def test_passing_control_back_resumes_the_agent_only_from_waiting_human(monkeypatch) -> None:
    session, _ = _wire(monkeypatch)
    statuses: list[str] = []

    async def open_conversation(session_, tenant_id, channel, customer_id):
        return SimpleNamespace(id=uuid.uuid4(), status="waiting_human")

    async def set_status(session_, tenant_id, conversation_id, status):
        statuses.append(status)

    monkeypatch.setattr(IngestService, "_open_conversation", open_conversation)
    monkeypatch.setattr(ConversationService, "set_status", set_status)

    applied = await IngestService.apply_handover(
        session, TENANT, "messenger", {"customer_ref": "psid-1", "event": "pass_thread_control"}
    )

    assert applied is True
    assert statuses == ["open"]


@pytest.mark.asyncio
async def test_request_thread_control_changes_nothing(monkeypatch) -> None:
    session, _ = _wire(monkeypatch)

    applied = await IngestService.apply_handover(
        session, TENANT, "messenger", {"customer_ref": "psid-1", "event": "request_thread_control"}
    )

    assert applied is False
