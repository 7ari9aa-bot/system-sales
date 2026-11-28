"""Who may touch a customer's Meta account through the template routes.

Submitting, syncing and deleting a template spend the customer's own WhatsApp business account,
so they need the stricter SEND grant and a connected channel, not just inbox read access.
"""

from __future__ import annotations

import pytest

from app.core.errors import ConflictError, PermissionDeniedError
from app.applications.apparel.modules.conversations.routers import templates as r

CONNECTED = {"access_token": "tok", "waba_id": "555"}


class Ctx:
    session = None
    tenant_id = "t"


def _patch(monkeypatch, *, allowed, sendable, config):
    async def a(ctx):
        return allowed

    async def s(ctx):
        return sendable

    async def c(ctx, provider):
        assert provider == "whatsapp"
        return config

    monkeypatch.setattr(r, "_allowed_channels", a)
    monkeypatch.setattr(r, "_sendable_channels", s)
    monkeypatch.setattr(r, "_channel_config", c)


async def test_a_user_with_whatsapp_and_send_gets_the_credentials(monkeypatch):
    _patch(monkeypatch, allowed={"whatsapp"}, sendable={"whatsapp"}, config=CONNECTED)
    assert await r._whatsapp_credentials(Ctx()) == CONNECTED


async def test_none_means_unrestricted(monkeypatch):
    _patch(monkeypatch, allowed=None, sendable=None, config=CONNECTED)
    assert await r._whatsapp_credentials(Ctx()) == CONNECTED


async def test_a_user_without_the_channel_is_refused(monkeypatch):
    # The send grant alone must not be enough: the channel itself has to be enabled for them.
    _patch(monkeypatch, allowed={"telegram"}, sendable={"whatsapp"}, config=CONNECTED)
    with pytest.raises(PermissionDeniedError, match="channel is not enabled"):
        await r._whatsapp_credentials(Ctx())


async def test_read_only_access_is_not_enough_to_spend_the_meta_account(monkeypatch):
    _patch(monkeypatch, allowed={"whatsapp"}, sendable={"telegram"}, config=CONNECTED)
    with pytest.raises(PermissionDeniedError, match="sending is not enabled"):
        await r._whatsapp_credentials(Ctx())


@pytest.mark.parametrize("config", [None, {}, {"waba_id": "555"}])
async def test_a_channel_that_is_not_connected_is_a_clear_conflict(monkeypatch, config):
    _patch(monkeypatch, allowed=None, sendable=None, config=config)
    with pytest.raises(ConflictError, match="not connected"):
        await r._whatsapp_credentials(Ctx())


def test_the_output_never_carries_credentials_and_says_who_reviews():
    from types import SimpleNamespace

    t = SimpleNamespace(
        id="1",
        name="n",
        status="submitted",
        language="ar",
        provider="whatsapp",
        body_text="b",
        variables=[],
        provider_template_id="9",
        category="UTILITY",
        components=[{"type": "BODY", "text": "b"}],
        rejection_reason=None,
        version=1,
        created_at=None,
        access_token="SECRET",
    )
    out = r._template_out(t)
    assert out["meta_managed"] is True and out["category"] == "UTILITY"
    assert "SECRET" not in str(out) and "access_token" not in out


def test_sync_is_registered_and_cannot_be_read_as_a_template_id():
    paths = {(m, x.path) for x in r.templates_router.routes for m in x.methods}
    assert ("POST", "/message-templates/sync") in paths
    # a UUID path param can never swallow "sync": it has no second segment
    assert ("POST", "/message-templates/{template_id}") not in paths
