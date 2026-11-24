"""Coexistence lifecycle: the merchant takes our app off, Meta offboards, or the account returns.

Three failures this closes:

* ``account_update`` was routed by ``entry.id``, which for a coexistence number is not always the
  business account — so the event landed on a channel that does not exist and was dropped;
* ``PARTNER_REMOVED`` / ``ACCOUNT_OFFBOARDED`` were not read at all, so a channel that could no
  longer send stayed ``active`` and kept "answering" people who would never receive it;
* nothing distinguished "the account came back" from "the channel is healthy": coming back needs
  the number verified again before anything is sent.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.conversations.gateway.ingest import _apply_account_signals
from app.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.modules.platform.models import Integration

pytestmark = pytest.mark.asyncio

WABA = "1001"


def _account_update(event: str, *, waba: str | None = WABA, **value_extra) -> dict:
    value = {"messaging_product": "whatsapp", "event": event, **value_extra}
    if waba:
        value["waba_info"] = {"waba_id": waba}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                # Meta does not promise the business account here; the waba_info block is the
                # documented place for a coexistence event.
                "id": "PHONE_NUMBER_ID_NOT_WABA",
                "changes": [{"field": "account_update", "value": value}],
            }
        ],
    }


# ------------------------------------------------------------------ parsing


def test_a_partner_removal_is_read_as_offboarding() -> None:
    signals = WhatsAppAdapter().parse_account_signals(_account_update("PARTNER_REMOVED"))
    assert [s["kind"] for s in signals] == ["offboarded"]
    assert signals[0]["waba_id"] == WABA


def test_an_offboarded_account_is_the_same_thing() -> None:
    signals = WhatsAppAdapter().parse_account_signals(_account_update("ACCOUNT_OFFBOARDED"))
    assert signals[0]["kind"] == "offboarded"


def test_the_official_disconnection_info_is_kept_for_the_screen() -> None:
    signals = WhatsAppAdapter().parse_account_signals(
        _account_update(
            "PARTNER_REMOVED",
            disconnection_info={"reason": "merchant_unlinked", "initiated_by": "BUSINESS"},
        )
    )
    assert signals[0]["reason"] == "merchant_unlinked"
    assert signals[0]["initiated_by"] == "BUSINESS"


def test_a_reconnected_account_is_read_as_reconnected() -> None:
    signals = WhatsAppAdapter().parse_account_signals(_account_update("ACCOUNT_RECONNECTED"))
    assert signals[0]["kind"] == "reconnected"


def test_a_restriction_still_parses_unchanged() -> None:
    signals = WhatsAppAdapter().parse_account_signals(
        _account_update("ACCOUNT_RESTRICTION", restriction_info=[{"restriction_type": "POLICY"}])
    )
    assert signals[0]["kind"] == "restriction"


def test_an_unrelated_account_update_is_still_ignored() -> None:
    assert WhatsAppAdapter().parse_account_signals(_account_update("PRICING_TIER_UPDATE")) == []


def test_the_envelope_is_placed_by_the_waba_not_by_entry_id() -> None:
    """`entry.id` is not the business account for a coexistence number."""
    assert WhatsAppAdapter().resolve_template_account(_account_update("PARTNER_REMOVED")) == WABA


def test_an_envelope_without_waba_info_falls_back_to_entry_id() -> None:
    payload = _account_update("PARTNER_REMOVED", waba=None)
    assert WhatsAppAdapter().resolve_template_account(payload) == "PHONE_NUMBER_ID_NOT_WABA"


# ------------------------------------------------------------------ applying


async def _channel(session, tenant_id, *, status: str = "active") -> Integration:
    integration = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider="whatsapp",
        kind="channel",
        config={"phone_number_id": "456", "waba_id": WABA},
        credentials={},
        status=status,
    )
    session.add(integration)
    await session.flush()
    return integration


async def test_a_partner_removal_disconnects_the_channel(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    integration = await _channel(session, tenant_id)

    await _apply_account_signals(
        session,
        tenant_id,
        "whatsapp",
        [{"kind": "offboarded", "event": "PARTNER_REMOVED", "waba_id": WABA, "reason": "unlinked"}],
    )

    assert integration.status == "disconnected"
    assert integration.webhook_health["partner_removed"]["reason"] == "unlinked"


async def test_a_reconnect_needs_the_number_verified_again(tenant_ctx) -> None:
    """Coming back is not proof the channel works: it waits for a connect, not for a send."""
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    integration = await _channel(session, tenant_id, status="disconnected")

    await _apply_account_signals(
        session, tenant_id, "whatsapp", [{"kind": "reconnected", "event": "ACCOUNT_RECONNECTED"}]
    )

    assert integration.status == "reauth_required"


async def test_a_restriction_still_restricts(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    integration = await _channel(session, tenant_id)

    await _apply_account_signals(
        session,
        tenant_id,
        "whatsapp",
        [{"kind": "restriction", "event": "ACCOUNT_RESTRICTION", "detail": "POLICY"}],
    )

    assert integration.status == "restricted"


async def test_offboarding_never_revives_a_channel_the_owner_disabled(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    integration = await _channel(session, tenant_id, status="disabled")

    await _apply_account_signals(
        session, tenant_id, "whatsapp", [{"kind": "offboarded", "event": "PARTNER_REMOVED"}]
    )

    assert integration.status == "disabled"
