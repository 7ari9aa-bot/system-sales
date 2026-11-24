"""Business-Scoped User IDs: a customer who shares no phone number is still a customer.

WhatsApp used to identify everyone by a phone number. A coexistence number also sees people who
share a BSUID instead — and the parser read `from` only, so those messages arrived with an EMPTY
customer ref. Every one of them collapsed onto the same blank identity: two different people in one
thread, and a reply sent to nobody.

The rule now: the phone when there is one, the BSUID when there is not, and a message naming
neither is dropped at the parser and refused at ingest.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.modules.customers.models import CustomerIdentity

pytestmark = pytest.mark.asyncio

BSUID = "EG.1234567890123456"


def _payload(*messages: dict, contacts: list | None = None) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1001",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "456"},
                            "contacts": contacts or [],
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


def _text(mid: str = "wamid.1", **overrides) -> dict:
    message = {
        "id": mid,
        "timestamp": "1700000000",
        "type": "text",
        "text": {"body": "السلام عليكم"},
    }
    message.update(overrides)
    return message


# ------------------------------------------------------------------ parsing


def test_a_number_less_customer_is_identified_by_their_bsuid() -> None:
    messages = WhatsAppAdapter().parse_inbound(_payload(_text(from_user_id=BSUID)))
    assert len(messages) == 1
    assert messages[0].customer_ref == BSUID
    assert messages[0].identity_type == "bsuid"


def test_a_phone_customer_keeps_the_phone_as_their_identity() -> None:
    messages = WhatsAppAdapter().parse_inbound(_payload(_text(**{"from": "201111111111"})))
    assert messages[0].customer_ref == "201111111111"
    assert messages[0].identity_type == "phone"


def test_the_phone_wins_when_meta_sends_both() -> None:
    """A BSUID is a fallback, not a replacement: the phone is what the merchant knows."""
    messages = WhatsAppAdapter().parse_inbound(
        _payload(_text(**{"from": "201111111111", "from_user_id": BSUID}))
    )
    assert messages[0].customer_ref == "201111111111"
    assert messages[0].identity_type == "phone"


def test_a_bsuid_only_customer_still_gets_their_name_and_username() -> None:
    """Contacts are keyed by user_id too — otherwise a BSUID thread reads as a bare id."""
    messages = WhatsAppAdapter().parse_inbound(
        _payload(
            _text(from_user_id=BSUID),
            contacts=[{"user_id": BSUID, "profile": {"name": "منى"}, "username": "mona_shops"}],
        )
    )
    assert messages[0].customer_name == "منى"
    assert messages[0].username == "mona_shops"


def test_the_business_parent_is_kept_when_meta_sends_it() -> None:
    messages = WhatsAppAdapter().parse_inbound(
        _payload(_text(from_user_id=BSUID, from_parent_user_id="EG.PARENT"))
    )
    assert messages[0].parent_ref == "EG.PARENT"


def test_a_message_that_names_nobody_is_not_a_customer_turn() -> None:
    """No phone and no BSUID: storing it would give every such message ONE blank identity."""
    assert WhatsAppAdapter().parse_inbound(_payload(_text())) == []


def test_a_real_message_survives_beside_an_anonymous_one() -> None:
    messages = WhatsAppAdapter().parse_inbound(
        _payload(_text("wamid.anon"), _text("wamid.real", from_user_id=BSUID))
    )
    assert [m.channel_message_id for m in messages] == ["wamid.real"]


# ------------------------------------------------------------------ ingest


async def test_ingest_refuses_a_message_with_no_identity(tenant_ctx) -> None:
    """Second line of defence: an adapter bug must never create a blank shared identity."""
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    with pytest.raises(ValidationError, match="customer identity"):
        await IngestService.ingest(
            session,
            tenant_id=tenant_id,
            message=InboundMessage(
                channel="whatsapp",
                channel_message_id="wamid.blank",
                customer_ref="",
                body="hi",
            ),
            idempotency_scope="test",
        )


async def test_a_bsuid_customer_is_stored_with_the_identity_type(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    conversation_id = await IngestService.ingest(
        session,
        tenant_id=tenant_id,
        message=InboundMessage(
            channel="whatsapp",
            channel_message_id="wamid.bsuid",
            customer_ref=BSUID,
            identity_type="bsuid",
            username="mona_shops",
            parent_ref="EG.PARENT",
            body="السلام عليكم",
        ),
        idempotency_scope="test",
    )
    assert conversation_id is not None
    identity = (
        (
            await session.execute(
                CustomerIdentity.__table__.select().where(
                    CustomerIdentity.tenant_id == tenant_id,
                    CustomerIdentity.external_id == BSUID,
                )
            )
        )
        .mappings()
        .one()
    )
    assert identity["extra"]["identity_type"] == "bsuid"
    assert identity["extra"]["username"] == "mona_shops"
    assert identity["extra"]["parent_ref"] == "EG.PARENT"


async def test_two_different_bsuids_are_two_different_customers(tenant_ctx) -> None:
    """The bug this replaces: both used to land on one blank identity."""
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    ids = set()
    for index, ref in enumerate((BSUID, f"{BSUID}.2")):
        ids.add(
            await IngestService.ingest(
                session,
                tenant_id=tenant_id,
                message=InboundMessage(
                    channel="whatsapp",
                    channel_message_id=f"wamid.multi.{index}",
                    customer_ref=ref,
                    identity_type="bsuid",
                    body="hi",
                ),
                idempotency_scope="test",
            )
        )
    assert len(ids) == 2
    assert uuid.UUID(str(next(iter(ids)))) is not None
