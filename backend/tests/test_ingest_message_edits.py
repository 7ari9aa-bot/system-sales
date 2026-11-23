"""An edited message changes the row we already hold, and never becomes a new one.

`message_edits` is subscribed on the Page, so Meta now sends the mid and the new text. Without a
handler the edit was dropped and the thread kept showing text the customer had already changed.
The rules: rewrite the body, keep what it said before, never cross a tenant boundary, never
create a message, and never fan it out to the agent as if the customer had spoken.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.messenger import MessengerAdapter

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, row=None) -> None:
        self.row = row
        self.executed = 0

    async def execute(self, stmt):
        self.executed += 1
        return _Result(self.row)


def _message(body="النص القديم", channel="messenger", metadata=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        body=body,
        channel=channel,
        edited=False,
        provider_metadata=dict(metadata or {}),
        conversation_id=uuid.uuid4(),
    )


def _payload(edits, sender="psid-1") -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "messaging": [
                    {
                        "sender": {"id": sender},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1700000000000,
                        "message_edits": edits,
                    }
                ],
            }
        ]
    }


def test_the_parser_reads_the_mid_and_the_new_text():
    edits = MessengerAdapter().parse_edits(_payload([{"mid": "m-1", "text": "النص الجديد"}]))

    assert len(edits) == 1
    assert edits[0]["mid"] == "m-1"
    assert edits[0]["text"] == "النص الجديد"
    assert edits[0]["customer_ref"] == "psid-1"


def test_a_bare_mid_is_still_reported_so_the_marker_can_be_set():
    edits = MessengerAdapter().parse_edits(_payload(["m-9"]))

    assert edits == [
        {
            "customer_ref": "psid-1",
            "recipient_ref": "page-1",
            "mid": "m-9",
            "text": None,
            "timestamp": 1700000000000,
        }
    ]


def test_a_payload_without_edits_reports_none():
    payload = {"object": "page", "entry": [{"id": "p", "messaging": [{"sender": {"id": "x"}}]}]}

    assert MessengerAdapter().parse_edits(payload) == []


@pytest.mark.asyncio
async def test_an_edit_rewrites_the_body_and_keeps_the_original():
    row = _message()
    session = _Session(row)

    updated = await IngestService.apply_edits(
        session, TENANT, "messenger", [{"mid": "m-1", "text": "النص الجديد", "timestamp": 5}]
    )

    assert updated == 1
    assert row.body == "النص الجديد"
    assert row.edited is True
    assert row.provider_metadata["original_body"] == "النص القديم"
    assert row.provider_metadata["edited_at"] == 5


@pytest.mark.asyncio
async def test_a_second_edit_does_not_overwrite_the_original():
    row = _message(metadata={"original_body": "الأصلي"})
    session = _Session(row)

    await IngestService.apply_edits(session, TENANT, "messenger", [{"mid": "m-1", "text": "تاني"}])

    assert row.body == "تاني"
    assert row.provider_metadata["original_body"] == "الأصلي", "the first text was lost"


@pytest.mark.asyncio
async def test_a_mid_we_do_not_hold_is_ignored_and_creates_nothing(monkeypatch):
    session = _Session(None)
    created: list[dict] = []

    async def add_message(session_, tenant_id, **kwargs):  # pragma: no cover - must not run
        created.append(kwargs)

    from app.modules.conversations.service import ConversationService

    monkeypatch.setattr(ConversationService, "add_message", add_message)

    updated = await IngestService.apply_edits(
        session, OTHER_TENANT, "messenger", [{"mid": "not-ours", "text": "x"}]
    )

    assert updated == 0
    assert created == []


@pytest.mark.asyncio
async def test_an_edit_for_another_channel_is_not_applied():
    row = _message(channel="instagram")
    session = _Session(row)

    updated = await IngestService.apply_edits(
        session, TENANT, "messenger", [{"mid": "m-1", "text": "x"}]
    )

    assert updated == 0
    assert row.body == "النص القديم"
