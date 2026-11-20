"""Meta's "template review state changed" event: detection, routing, and the re-sync it triggers.

The event names the WhatsApp Business Account and carries no phone number, so the usual
phone-number routing cannot place it. It is treated as a signal only: the store's templates are
re-read from Meta, and nothing the event says is ever written to our data.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter as adapter
from app.modules.platform.models import WebhookEvent

FIELD = "message_template_status_update"


def _template_change(**value) -> dict:
    return {"field": FIELD, "value": {"event": "APPROVED", "message_template_name": "x", **value}}


def _message_change(phone: str = "P1") -> dict:
    return {
        "field": "messages",
        "value": {"metadata": {"phone_number_id": phone}, "messages": []},
    }


def _payload(*entries: tuple[str, list[dict]]) -> dict:
    return {"entry": [{"id": account, "changes": changes} for account, changes in entries]}


# ------------------------------------------------------------------ detection


def test_a_template_only_envelope_names_its_business_account():
    payload = _payload(("WABA-1", [_template_change()]))
    assert adapter.resolve_template_account(payload) == "WABA-1"
    assert adapter.has_template_status_change(payload) is True


def test_several_template_changes_for_one_account_still_name_it():
    payload = _payload(("WABA-1", [_template_change(), _template_change()]))
    assert adapter.resolve_template_account(payload) == "WABA-1"


def test_an_envelope_naming_two_accounts_is_not_placed():
    payload = _payload(("WABA-1", [_template_change()]), ("WABA-2", [_template_change()]))
    assert adapter.resolve_template_account(payload) is None


def test_an_envelope_mixing_in_messages_keeps_its_normal_routing():
    payload = _payload(("WABA-1", [_template_change(), _message_change()]))
    assert adapter.resolve_template_account(payload) is None
    # ...but the template news in it is still noticed when it is processed.
    assert adapter.has_template_status_change(payload) is True


def test_a_message_only_envelope_is_not_template_news():
    payload = _payload(("WABA-1", [_message_change()]))
    assert adapter.resolve_template_account(payload) is None
    assert adapter.has_template_status_change(payload) is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"entry": []},
        {"entry": ["not-a-dict"]},
        {"entry": [{"id": "WABA-1"}]},
        {"entry": [{"id": "WABA-1", "changes": []}]},
        {"entry": [{"id": "WABA-1", "changes": ["junk"]}]},
        {"entry": [{"id": "", "changes": [_template_change()]}]},
        {"entry": [{"changes": [_template_change()]}]},
        {"entry": [{"id": None, "changes": [_template_change()]}]},
    ],
)
def test_malformed_or_unattributed_envelopes_are_never_placed(payload):
    assert adapter.resolve_template_account(payload) is None


# ------------------------------------------------------------------ routing


async def test_a_template_event_is_queued_under_the_store_that_owns_the_account(
    db, tenant_ctx, monkeypatch
):
    import app.modules.conversations.routers.webhooks as hooks

    seen: dict = {}

    async def _by_phone(_session, _channel, key):
        seen["phone_key"] = key
        return None  # a template event has no phone number

    async def _by_account(_session, waba):
        seen["waba"] = waba
        return tenant_ctx.tenant_id

    monkeypatch.setattr(IngestService, "resolve_tenant", staticmethod(_by_phone))
    monkeypatch.setattr(IngestService, "resolve_account_tenant", staticmethod(_by_account))
    monkeypatch.setattr(adapter, "check_signature", lambda _h, _b: True)

    payload = _payload(("WABA-9", [_template_change()]))
    out = await hooks._ingest_one(db, "whatsapp", adapter, payload, b'{"entry":1}')

    assert out == {"ok": True, "queued": True}
    assert seen["waba"] == "WABA-9"
    rows = (
        (
            await db.execute(
                select(WebhookEvent).where(WebhookEvent.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_a_template_event_for_an_unknown_or_ambiguous_account_is_acked_and_dropped(
    db, tenant_ctx, monkeypatch
):
    import app.modules.conversations.routers.webhooks as hooks

    async def _nobody(*_args):
        return None

    monkeypatch.setattr(IngestService, "resolve_tenant", staticmethod(_nobody))
    monkeypatch.setattr(IngestService, "resolve_account_tenant", staticmethod(_nobody))

    out = await hooks._ingest_one(
        db, "whatsapp", adapter, _payload(("WABA-?", [_template_change()])), b"{}"
    )

    assert out.get("ok") is True
    assert not out.get("queued")
    rows = (await db.execute(select(WebhookEvent))).scalars().all()
    assert rows == []


async def test_a_message_delivery_never_asks_for_an_account_lookup(db, tenant_ctx, monkeypatch):
    """An ordinary message resolves by phone number; the account lookup stays out of its way."""
    import app.modules.conversations.routers.webhooks as hooks

    async def _by_phone(*_args):
        return tenant_ctx.tenant_id

    async def _boom(*_args):
        raise AssertionError("account lookup must not run for a delivery the phone key placed")

    monkeypatch.setattr(IngestService, "resolve_tenant", staticmethod(_by_phone))
    monkeypatch.setattr(IngestService, "resolve_account_tenant", staticmethod(_boom))

    out = await hooks._ingest_one(
        db, "whatsapp", adapter, _payload(("WABA-1", [_message_change("P1")])), b'{"m":1}'
    )
    assert out == {"ok": True, "queued": True}


# ------------------------------------------------------------------ processing


async def _event(db, tenant_id, payload) -> WebhookEvent:
    event = WebhookEvent(
        provider="whatsapp",
        external_event_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        signature_valid=True,
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    await db.flush()
    return event


def _patch_sync(monkeypatch, *, creds, calls, raises=None):
    import app.modules.conversations.templates as templates
    import app.modules.platform.services.channel_access as access

    async def _creds(_session, tenant_id, provider):
        calls.setdefault("creds_for", []).append((tenant_id, provider))
        return creds

    async def _sync(_session, tenant_id, *, credentials, _client=None):
        calls.setdefault("synced", []).append((tenant_id, credentials))
        if raises:
            raise raises
        return {"checked": 1, "changed": [], "missing_on_meta": []}

    monkeypatch.setattr(access, "channel_credentials_config", _creds)
    monkeypatch.setattr(templates.TemplateService, "sync_from_meta", staticmethod(_sync))


async def _process(db, tenant_id, payload):
    event = await _event(db, tenant_id, payload)
    accepted = await IngestService.process_webhook_event(
        db,
        adapter=adapter,
        channel="whatsapp",
        tenant_id=tenant_id,
        event_id=event.id,
        payload=payload,
    )
    await db.refresh(event)
    return accepted, event


async def test_processing_a_template_event_re_reads_the_templates_from_meta(
    db, tenant_ctx, monkeypatch
):
    calls: dict = {}
    _patch_sync(monkeypatch, creds={"access_token": "tok", "waba_id": "W"}, calls=calls)

    _, event = await _process(
        db, tenant_ctx.tenant_id, _payload(("W", [_template_change(event="REJECTED")]))
    )

    assert event.processing_status == "processed"
    assert calls["synced"] == [(tenant_ctx.tenant_id, {"access_token": "tok", "waba_id": "W"})]


async def test_the_event_s_own_claims_are_never_written(db, tenant_ctx, monkeypatch):
    """A forged 'APPROVED' must change nothing by itself: only Meta's own list can."""
    from app.modules.conversations.templates import TemplateService

    calls: dict = {}
    _patch_sync(monkeypatch, creds={"access_token": "tok"}, calls=calls)
    forbidden = []

    async def _no_write(*args, **kwargs):
        forbidden.append(args)

    monkeypatch.setattr(TemplateService, "apply_remote_status", _no_write, raising=False)

    await _process(
        db,
        tenant_ctx.tenant_id,
        _payload(("W", [_template_change(event="APPROVED", message_template_name="evil")])),
    )

    assert forbidden == []
    assert len(calls["synced"]) == 1  # the only effect is a fresh read from Meta


async def test_a_meta_failure_does_not_lose_the_event_or_the_messages(db, tenant_ctx, monkeypatch):
    calls: dict = {}
    _patch_sync(
        monkeypatch,
        creds={"access_token": "tok"},
        calls=calls,
        raises=RuntimeError("meta is down"),
    )

    accepted, event = await _process(
        db, tenant_ctx.tenant_id, _payload(("W", [_template_change()]))
    )

    assert event.processing_status == "processed"  # not quarantined, not rolled back
    assert accepted == 0
    assert len(calls["synced"]) == 1


async def test_a_store_without_a_usable_token_is_left_alone(db, tenant_ctx, monkeypatch):
    for creds in (None, {}, {"waba_id": "W"}, {"access_token": ""}):
        calls: dict = {}
        _patch_sync(monkeypatch, creds=creds, calls=calls)
        _, event = await _process(db, tenant_ctx.tenant_id, _payload(("W", [_template_change()])))
        assert event.processing_status == "processed"
        assert "synced" not in calls


async def test_an_ordinary_message_delivery_does_not_touch_meta(db, tenant_ctx, monkeypatch):
    calls: dict = {}
    _patch_sync(monkeypatch, creds={"access_token": "tok"}, calls=calls)

    await _process(db, tenant_ctx.tenant_id, _payload(("W", [_message_change("P1")])))

    assert "creds_for" not in calls
    assert "synced" not in calls
