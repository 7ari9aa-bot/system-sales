"""A new Messenger thread must not stay a bare number: the profile read is scheduled at ingest.

The read talks to Meta, so it must never sit in front of the webhook's 200 and must never be
able to fail the message that triggered it. These tests pin both rules without a database.
"""

from __future__ import annotations

import uuid

import pytest

from app.applications.apparel.modules.conversations.gateway import ingest as ingest_module


class _Scheduled:
    def __init__(self) -> None:
        self.coros: list = []

    def __call__(self, coro):
        self.coros.append(coro)
        coro.close()  # never awaited here; closing keeps the warning away
        return None


@pytest.fixture
def scheduled(monkeypatch):
    spy = _Scheduled()
    monkeypatch.setattr(ingest_module.asyncio, "create_task", spy)
    return spy


@pytest.mark.parametrize("channel", ["messenger", "instagram"])
def test_a_meta_customer_profile_is_read_after_ingest(scheduled, channel):
    ingest_module.IngestService._enrich_profile_soon(uuid.uuid4(), uuid.uuid4(), channel)
    assert len(scheduled.coros) == 1


@pytest.mark.parametrize("channel", ["whatsapp", "telegram", "email", "webchat"])
def test_other_channels_send_their_name_in_the_webhook(scheduled, channel):
    """WhatsApp and Telegram already deliver a name, so no read is scheduled for them."""
    ingest_module.IngestService._enrich_profile_soon(uuid.uuid4(), uuid.uuid4(), channel)
    assert scheduled.coros == []


def test_a_missing_event_loop_is_not_an_ingest_failure(monkeypatch):
    """A CLI replay or a sync test has no loop: the courtesy is skipped, the message is not."""

    def _boom(coro):
        coro.close()
        raise RuntimeError("no running event loop")

    monkeypatch.setattr(ingest_module.asyncio, "create_task", _boom)
    ingest_module.IngestService._enrich_profile_soon(uuid.uuid4(), uuid.uuid4(), "messenger")
