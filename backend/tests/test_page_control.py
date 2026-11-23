"""A reply typed in Meta's inbox shows up here, and the AI stands down when a human has the thread.

Echoes and thread-control events were parsed and then dropped by the ingest. These tests drive the
service that now records them, with a fake session that answers the queries it issues.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.conversations.gateway import page_control
from app.modules.conversations.gateway.messenger import messenger_adapter

OURS = "999000111"
TENANT = uuid.uuid4()
USER = "psid-1"
PAGE = "page-1"


def _envelope(*events):
    return {"object": "page", "entry": [{"id": PAGE, "messaging": list(events)}]}


def _echo(mid="m.echo", text="we are open till 9", app_id=None):
    message = {"mid": mid, "is_echo": True, "text": text}
    if app_id is not None:
        message["app_id"] = app_id
    return {"sender": {"id": PAGE}, "recipient": {"id": USER}, "timestamp": 1, "message": message}


def _media_echo(mid, attachments, text=None):
    """A reply typed in the Page inbox that carries a photo, a voice note or a file."""
    message = {"mid": mid, "is_echo": True, "attachments": attachments}
    if text is not None:
        message["text"] = text
    return {"sender": {"id": PAGE}, "recipient": {"id": USER}, "timestamp": 1, "message": message}


def _att(kind, url="https://cdn.example/x"):
    return {"type": kind, "payload": {"url": url}}


def _handover(kind, new_owner, previous=""):
    return {
        "sender": {"id": USER},
        "recipient": {"id": PAGE},
        "timestamp": 1,
        kind: {"new_owner_app_id": new_owner, "previous_owner_app_id": previous},
    }


class _Rows:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def first(self):
        return None if self.value is None else (self.value,)


class _Session:
    """Answers, in order: customer id lookup, conversation lookup, then any message-id lookups."""

    def __init__(self, conversation, *, known_mids=(), customer=True):
        self.conversation = conversation
        self.known = set(known_mids)
        self.customer = uuid.uuid4() if customer else None
        self.added = []
        self.calls = 0

    async def execute(self, statement):
        self.calls += 1
        sql = str(statement)
        if "customer_identities" in sql:
            return _Rows(self.customer)
        if "FROM conversations" in sql:
            return _Rows(self.conversation)
        # the message-id dedupe lookup
        compiled = statement.compile().params
        return _Rows(1 if any(v in self.known for v in compiled.values()) else None)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None


def _conversation(status="open"):
    return SimpleNamespace(
        id=uuid.uuid4(), channel="messenger", status=status, last_message_at=None
    )


@pytest.fixture(autouse=True)
def _sla(monkeypatch):
    calls = []

    async def mark_met(session, tenant_id, *, conversation_id, **_kw):
        calls.append(conversation_id)

    monkeypatch.setattr("app.modules.operations.sla.SlaService.mark_met", mark_met)
    return calls


# ------------------------------------------------------------------ echoes


async def test_a_reply_with_only_a_photo_is_stored_not_dropped():
    """A photo sent from Meta Business Suite has no text. It used to vanish, leaving the
    customer's last message looking unanswered and the AI free to answer it again."""
    conv = _conversation()
    session = _Session(conv)
    echoes = messenger_adapter.parse_echoes(_envelope(_media_echo("m.photo", [_att("image")])))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 1
    )
    [row] = session.added
    assert (row.direction, row.sender_type, row.status) == ("outbound", "agent", "sent")
    assert row.channel_message_id == "m.photo" and row.body is None
    assert (row.content_type, row.media_type) == ("image", "image")
    assert row.media_url == "https://cdn.example/x"
    assert conv.status == "waiting_human"  # a person answered, so the AI stands down


async def test_a_photo_with_a_caption_keeps_both():
    session = _Session(_conversation())
    echoes = messenger_adapter.parse_echoes(
        _envelope(_media_echo("m.cap", [_att("image")], text="the blue one"))
    )
    await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS)
    [row] = session.added
    assert row.body == "the blue one" and row.content_type == "image"


async def test_an_album_becomes_one_message_per_attachment_and_only_the_first_has_the_caption():
    session = _Session(_conversation())
    atts = [_att("image", "https://cdn/1"), _att("video", "https://cdn/2"), _att("file", "u3")]
    echoes = messenger_adapter.parse_echoes(_envelope(_media_echo("m.album", atts, text="menu")))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 3
    )
    assert [r.channel_message_id for r in session.added] == ["m.album", "m.album#1", "m.album#2"]
    assert [r.content_type for r in session.added] == ["image", "video", "file"]
    assert [r.body for r in session.added] == ["menu", None, None]


async def test_a_redelivered_album_adds_only_what_is_missing():
    session = _Session(_conversation(), known_mids={"m.album"})
    atts = [_att("image", "https://cdn/1"), _att("image", "https://cdn/2")]
    echoes = messenger_adapter.parse_echoes(_envelope(_media_echo("m.album", atts)))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 1
    )
    assert [r.channel_message_id for r in session.added] == ["m.album#1"]


async def test_a_voice_note_is_a_voice_message():
    session = _Session(_conversation())
    echoes = messenger_adapter.parse_echoes(_envelope(_media_echo("m.v", [_att("audio")])))
    await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS)
    assert session.added[0].content_type == "voice"


async def test_an_attachment_without_a_link_is_still_recorded_as_unsupported():
    """Meta can omit the url (a sticker, a template). The reply still happened, so the thread
    shows that something was sent instead of pretending nothing was."""
    session = _Session(_conversation())
    echoes = messenger_adapter.parse_echoes(
        _envelope(_media_echo("m.s", [{"type": "template", "payload": {}}]))
    )
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 1
    )
    [row] = session.added
    assert row.content_type == "unsupported" and row.media_url is None and row.media_type is None


async def test_an_echo_with_neither_words_nor_attachments_is_still_skipped():
    session = _Session(_conversation())
    echoes = messenger_adapter.parse_echoes(_envelope(_media_echo("m.empty", [])))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 0
    )
    assert session.added == []


async def test_a_reply_typed_in_the_page_inbox_is_stored_as_a_sent_agent_message(_sla):
    conv = _conversation()
    session = _Session(conv)
    echoes = messenger_adapter.parse_echoes(_envelope(_echo()))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 1
    )
    [row] = session.added
    assert (row.direction, row.sender_type, row.status) == ("outbound", "agent", "sent")
    assert row.channel_message_id == "m.echo" and row.body == "we are open till 9"
    assert row.provider_metadata["source"] == "page_inbox_echo"
    assert _sla == [conv.id]  # the first-response clock is met
    assert conv.status == "waiting_human"  # the AI must not talk over the person


async def test_our_own_send_echoed_back_is_ignored():
    session = _Session(_conversation())
    echoes = messenger_adapter.parse_echoes(_envelope(_echo(app_id=int(OURS))))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 0
    )
    assert session.added == []


async def test_an_echo_already_stored_is_not_stored_twice():
    session = _Session(_conversation(), known_mids={"m.echo"})
    echoes = messenger_adapter.parse_echoes(_envelope(_echo()))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 0
    )
    assert session.added == []


async def test_an_echo_for_a_customer_we_never_met_creates_nothing():
    session = _Session(None, customer=False)
    echoes = messenger_adapter.parse_echoes(_envelope(_echo()))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 0
    )
    assert session.added == []


async def test_an_echo_without_text_or_id_is_skipped():
    session = _Session(_conversation())
    echoes = [
        {"customer_ref": USER, "mid": "", "text": "x"},
        {"customer_ref": USER, "mid": "m", "text": ""},
    ]
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 0
    )


async def test_an_echo_does_not_reopen_a_thread_a_human_already_owns():
    conv = _conversation(status="waiting_human")
    session = _Session(conv)
    echoes = messenger_adapter.parse_echoes(_envelope(_echo()))
    await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS)
    assert conv.status == "waiting_human"


async def test_an_echo_never_raises_a_send(monkeypatch):
    """Recording an echo must not queue a send: it already left."""

    async def boom(*_a, **_k):
        raise AssertionError("an echo must not emit an outbound event")

    monkeypatch.setattr("app.core.events.writer.add_outbox_event", boom)
    session = _Session(_conversation())
    echoes = messenger_adapter.parse_echoes(_envelope(_echo()))
    assert (
        await page_control.record_echoes(session, TENANT, "messenger", echoes, own_app_id=OURS) == 1
    )


# ------------------------------------------------------------------ handovers


@pytest.fixture
def takeovers(monkeypatch):
    seen = []

    async def request_human_takeover(
        session, tenant_id, *, conversation_id, reason, note=None, run_id=None
    ):
        seen.append((conversation_id, reason, note))
        return True

    monkeypatch.setattr("app.modules.ai.handover.request_human_takeover", request_human_takeover)
    return seen


async def test_passing_the_thread_to_another_app_parks_the_conversation(takeovers):
    conv = _conversation()
    session = _Session(conv)
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("pass_thread_control", "inbox-app", OURS))
    )
    assert (
        await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
        == 1
    )
    assert takeovers == [(conv.id, page_control.HANDOVER_REASON, "Meta pass_thread_control")]


async def test_another_app_taking_the_thread_parks_it_too(takeovers):
    session = _Session(_conversation())
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("take_thread_control", "inbox-app", OURS))
    )
    assert (
        await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
        == 1
    )
    assert len(takeovers) == 1


async def test_control_coming_back_to_us_resumes_the_ai(takeovers):
    conv = _conversation(status="waiting_human")
    session = _Session(conv)
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("pass_thread_control", OURS, "inbox-app"))
    )
    assert (
        await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
        == 1
    )
    assert conv.status == "open" and takeovers == []


async def test_taking_control_back_resumes_the_ai(takeovers):
    conv = _conversation(status="waiting_human")
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("take_thread_control", OURS, "inbox-app"))
    )
    session = _Session(conv)
    await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
    assert conv.status == "open"


async def test_resuming_never_reopens_a_closed_or_paused_thread(takeovers):
    conv = _conversation(status="paused")
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("pass_thread_control", OURS, "inbox-app"))
    )
    session = _Session(conv)
    assert (
        await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
        == 0
    )
    assert conv.status == "paused"


async def test_a_handover_for_an_unknown_customer_changes_nothing(takeovers):
    session = _Session(None, customer=False)
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("pass_thread_control", "inbox-app", OURS))
    )
    assert (
        await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
        == 0
    )
    assert takeovers == []


async def test_a_thread_already_with_a_human_is_not_parked_twice(takeovers):
    conv = _conversation(status="waiting_human")
    session = _Session(conv)
    events = messenger_adapter.parse_handovers(
        _envelope(_handover("pass_thread_control", "inbox-app", OURS))
    )
    assert (
        await page_control.apply_handovers(session, TENANT, "messenger", events, own_app_id=OURS)
        == 0
    )
    assert takeovers == []


# ------------------------------------------------------------------ the wiring


def test_the_ingest_calls_both_parsers():
    import inspect

    from app.modules.conversations.gateway.ingest import IngestService

    source = inspect.getsource(IngestService.process_webhook_event)
    assert "parse_echoes" in source and "parse_handovers" in source
    assert "record_echoes" in source and "apply_handovers" in source


async def test_process_webhook_event_hands_echoes_and_handovers_to_the_service(monkeypatch):
    """The ingest really calls the service with what the adapter parsed, not just mentions it."""
    from app.modules.conversations.gateway.ingest import IngestService

    seen = {"echoes": None, "handovers": None}

    async def record_echoes(session, tenant_id, channel, echoes, *, own_app_id):
        seen["echoes"] = (channel, [e["mid"] for e in echoes], own_app_id)
        return len(echoes)

    async def apply_handovers(session, tenant_id, channel, handovers, *, own_app_id):
        seen["handovers"] = (channel, [h["event"] for h in handovers], own_app_id)
        return len(handovers)

    async def noop(*_a, **_k):
        return None

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class _Db:
        def begin_nested(self):
            return _Nested()

        async def execute(self, *_a, **_k):
            return SimpleNamespace(rowcount=1)

    monkeypatch.setattr("app.core.db.bind_tenant", noop)
    monkeypatch.setattr(page_control, "record_echoes", record_echoes)
    monkeypatch.setattr(page_control, "apply_handovers", apply_handovers)
    monkeypatch.setattr(IngestService, "fill_customer_names", noop)
    monkeypatch.setattr(IngestService, "apply_status_updates", noop)
    monkeypatch.setattr(IngestService, "apply_read_watermarks", noop)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(meta_app_id=f" {OURS} ")
    )

    payload = _envelope(_echo(mid="m.1"), _handover("pass_thread_control", "inbox-app", OURS))
    await IngestService.process_webhook_event(
        _Db(),
        adapter=messenger_adapter,
        channel="messenger",
        tenant_id=TENANT,
        event_id=uuid.uuid4(),
        payload=payload,
    )
    assert seen["echoes"] == ("messenger", ["m.1"], OURS)
    assert seen["handovers"] == ("messenger", ["pass_thread_control"], OURS)
