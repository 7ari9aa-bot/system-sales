"""The seen/typing recipient is the customer's id on the thread's OWN channel.

Instagram threads are addressed by the Instagram-scoped id, Messenger threads by the
page-scoped id (PSID). The service used to ask for the ``instagram`` identity no matter
which channel the conversation belonged to, which found no row for Messenger and turned
mark_seen and typing_on off there without any error.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.conversations import customer_profile
from app.modules.conversations.read_signal_service import ReadSignalService


class _Identities:
    def __init__(self, external_id: str | None) -> None:
        self.external_id = external_id
        self.calls: list[tuple] = []

    async def channel_identity(self, session, tenant_id, customer_id, channel):
        self.calls.append((tenant_id, customer_id, channel))
        return SimpleNamespace(external_id=self.external_id) if self.external_id else None


def _conversation(channel: str) -> SimpleNamespace:
    return SimpleNamespace(channel=channel, customer_id=uuid.uuid4(), id=uuid.uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["messenger", "instagram"])
async def test_the_identity_is_read_for_the_conversations_own_channel(
    monkeypatch, channel: str
) -> None:
    identities = _Identities("scoped-1")
    monkeypatch.setattr(customer_profile, "customers", lambda: identities)
    tenant_id = uuid.uuid4()
    conversation = _conversation(channel)

    ref = await ReadSignalService._customer_ref(None, tenant_id, conversation)

    assert ref == "scoped-1"
    assert identities.calls == [(tenant_id, conversation.customer_id, channel)]


@pytest.mark.asyncio
async def test_a_missing_identity_is_no_customer_rather_than_an_error(monkeypatch) -> None:
    monkeypatch.setattr(customer_profile, "customers", lambda: _Identities(None))

    assert (
        await ReadSignalService._customer_ref(None, uuid.uuid4(), _conversation("messenger"))
        is None
    )
