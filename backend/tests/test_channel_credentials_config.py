"""The one place another module asks platform for a channel's ready-to-use provider settings.

It exists so ``conversations`` imports neither the Integration table nor the credentials service
(each import there is a permanent coupling counted by test_module_boundaries). What it must keep:
the same audited decryption as every other reader, and nothing decrypted for a signal that was
never going to be sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.applications.apparel.modules.conversations.read_signal_service import ReadSignalService
from app.modules.platform.models import Integration
from app.modules.platform.services import channel_access
from tests.test_whatsapp_read_signal import _chat, _conversation, _Spy

pytestmark = pytest.mark.asyncio


@pytest.fixture
def spy(monkeypatch):
    """A stand-in provider adapter, so no network is touched."""
    s = _Spy()
    monkeypatch.setattr("app.applications.apparel.modules.conversations.read_signal_service.get_adapter", lambda name: s)
    return s


@pytest.fixture
def decrypts(monkeypatch):
    """Count decryptions; the secret part wins over what is stored in plain config."""
    seen: list[str] = []

    async def _decrypt(session, integration):
        seen.append(str(integration.id))
        return {"access_token": "secret-token", "phone_number_id": "from-secret"}

    monkeypatch.setattr(
        "app.modules.platform.services.secrets.IntegrationCredentialsService.decrypt", _decrypt
    )
    return seen


async def test_no_connection_is_none_and_nothing_is_decrypted(db, tenant_ctx, decrypts) -> None:
    out = await channel_access.channel_credentials_config(db, tenant_ctx.tenant_id, "whatsapp")
    assert out is None
    assert decrypts == []


async def test_the_decrypted_secrets_are_merged_over_the_stored_settings(
    db, tenant_ctx, decrypts
) -> None:
    db.add(
        Integration(
            tenant_id=tenant_ctx.tenant_id,
            provider="whatsapp",
            kind="channel",
            config={"phone_number_id": "from-config", "waba_id": "W1"},
        )
    )
    await db.flush()
    out = await channel_access.channel_credentials_config(db, tenant_ctx.tenant_id, "whatsapp")
    assert out == {
        "phone_number_id": "from-secret",
        "waba_id": "W1",
        "access_token": "secret-token",
    }
    assert len(decrypts) == 1


async def test_only_a_channel_of_the_asked_provider_is_returned(db, tenant_ctx, decrypts) -> None:
    db.add_all(
        [
            Integration(
                tenant_id=tenant_ctx.tenant_id, provider="telegram", kind="channel", config={}
            ),
            Integration(
                tenant_id=tenant_ctx.tenant_id, provider="whatsapp", kind="payment", config={}
            ),
        ]
    )
    await db.flush()
    assert (
        await channel_access.channel_credentials_config(db, tenant_ctx.tenant_id, "whatsapp")
        is None
    )
    assert decrypts == []


async def test_a_signal_that_is_never_sent_decrypts_nothing(db, tenant_ctx, spy, decrypts) -> None:
    """Outside the 24h window the signal stops before any credential is read, so the audit trail
    does not fill with "credentials read" rows for chats that merely got opened."""
    cid = await _chat(db, tenant_ctx)
    conv = await _conversation(db, cid)
    conv.last_customer_message_at = datetime.now(UTC) - timedelta(hours=25)
    await db.flush()

    async def load():
        return await channel_access.channel_credentials_config(db, tenant_ctx.tenant_id, "whatsapp")

    out = await ReadSignalService.send(
        db, tenant_ctx.tenant_id, conv, typing=False, load_channel_config=load
    )
    assert (out.sent, out.skipped) == (False, "window_closed")
    assert decrypts == []
    assert spy.calls == []


async def test_a_signal_that_is_sent_decrypts_once_and_uses_the_merged_settings(
    db, tenant_ctx, spy, decrypts
) -> None:
    cid = await _chat(db, tenant_ctx)
    conv = await _conversation(db, cid)
    captured: list[dict] = []
    real = spy.send_read_signal

    async def capture(credentials, provider_message_id, *, typing):
        captured.append(credentials.config)
        await real(credentials, provider_message_id, typing=typing)

    spy.send_read_signal = capture

    async def load():
        return await channel_access.channel_credentials_config(db, tenant_ctx.tenant_id, "whatsapp")

    out = await ReadSignalService.send(
        db, tenant_ctx.tenant_id, conv, typing=True, load_channel_config=load
    )
    assert out.sent is True
    assert len(decrypts) == 1
    assert captured == [{"phone_number_id": "from-secret", "access_token": "secret-token"}]
