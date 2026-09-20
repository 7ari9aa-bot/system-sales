"""G-09 — marketing consent is enforced before a promotional message is sent.

``Consent`` (privacy module) is a purpose- and channel-scoped append-only
ledger. Nothing consulted it before sending, so an opted-out customer could
still receive a promotion.

The `messages` table has no purpose/kind column (``content_type`` is a content
KIND, ``template_name`` is shared by transactional and promotional templates),
so a promotion cannot be *detected* — which means a "safe default purpose" is
not protection: omitting the argument would be the bypass. The design is
therefore structural: the generic outbound path has NO purpose argument and is
transactional by construction, and ``add_promotional_message`` is the single
door that produces ``purpose="marketing"`` and always runs the gate.

DB-free tests pin that structure and the decision branches; DB-backed tests
cover the real ledger and tenant scoping.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.consent import (
    CONSENT_PURPOSES,
    CONSENT_REQUIRED_PURPOSES,
    MARKETING_PURPOSE,
    evaluate_outbound_consent,
    purpose_requires_consent,
    validate_purpose,
)
from app.core.errors import ValidationError
from app.modules.conversations.policy import OutboundBlockedError
from app.modules.conversations.service import ConversationService

MARKETING = "50% off everything this weekend — shop now!"
TRANSACTIONAL = "Your order #1042 has shipped."


# ------------------------------------------------------- policy (no DB) ---


def test_only_marketing_requires_consent() -> None:
    assert CONSENT_REQUIRED_PURPOSES == frozenset({"marketing"})
    assert purpose_requires_consent("marketing")
    for purpose in ("service_messages", "ai_processing", "analytics"):
        assert not purpose_requires_consent(purpose)


def test_the_known_purposes_match_the_ledger() -> None:
    """The gate must not accept a purpose the Consent ledger cannot store."""
    assert CONSENT_PURPOSES == {
        "service_messages",
        "marketing",
        "ai_processing",
        "analytics",
    }


def test_an_unknown_purpose_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate_purpose("promo")


# ------------------------------------- the structure that closes the bypass --


def test_the_transactional_path_cannot_express_a_purpose() -> None:
    """The generic choke point has no purpose argument at all.

    This is the fix for the review: as long as `add_message` could take a
    `purpose`, omitting it was a silent bypass (a promotion is byte-identical to
    a shipping notice). Marketing is now not expressible here.
    """
    params = set(inspect.signature(ConversationService.add_message).parameters)
    assert "purpose" not in params


def test_the_marketing_door_has_nothing_to_forget() -> None:
    """`add_promotional_message` must not accept a purpose or an off switch."""
    params = set(inspect.signature(ConversationService.add_promotional_message).parameters)
    assert "purpose" not in params
    assert {"require_consent", "skip_consent", "check_consent"}.isdisjoint(params)


# ------------------------------------------- decision branches (no DB) -----


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Conversation:
    """Minimal conversation stub — webchat is unregulated (§30 cannot mask us)."""

    channel = "webchat"
    status = "open"
    last_customer_message_at = None
    last_message_at = None
    unread_count = 0
    messaging_policy_state = "open"

    def __init__(self):
        self.customer_id = uuid.uuid4()


class _Session:
    """Stands in for AsyncSession so the door can be exercised without a DB.

    Consent statements are answered from `consent_status`; every other statement
    (the conversation lookup) returns the stub conversation. `added` records any
    row the code tried to persist.
    """

    def __init__(self, consent_status):
        self._consent_status = consent_status
        self.conversation = _Conversation()
        self.statements: list[tuple[str, dict | None]] = []
        self.added: list = []
        self.flushed = False

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "FROM consents" in sql:
            return _Result(self._consent_status)
        return _Result(self.conversation)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True


def _consent_calls(session):
    return [(sql, params) for sql, params in session.statements if "FROM consents" in sql]


async def test_a_promotional_send_without_consent_is_refused_and_writes_nothing():
    session = _Session(consent_status=None)

    with pytest.raises(OutboundBlockedError) as exc:
        await ConversationService.add_promotional_message(
            session, uuid.uuid4(), conversation_id=uuid.uuid4(), body=MARKETING
        )
    assert "marketing" in str(exc.value)
    assert session.added == [], "a consent-blocked promotional message was written anyway"


async def test_the_marketing_door_always_consults_the_ledger_for_marketing():
    """If the door stops checking (or checks another purpose) this fails."""
    session = _Session(consent_status="granted")

    await ConversationService.add_promotional_message(
        session, uuid.uuid4(), conversation_id=uuid.uuid4(), body=MARKETING
    )

    calls = _consent_calls(session)
    assert calls, "the marketing door sent without consulting the consent ledger"
    assert calls[0][1]["purpose"] == MARKETING_PURPOSE == "marketing"


async def test_a_promotional_send_with_consent_reaches_the_transport():
    session = _Session(consent_status="granted")

    message = await ConversationService.add_promotional_message(
        session, uuid.uuid4(), conversation_id=uuid.uuid4(), body=MARKETING
    )
    assert message.body == MARKETING
    assert session.added, "the allowed promotional message was never written"


async def test_a_granted_consent_allows_and_a_revoked_one_refuses():
    allowed = await evaluate_outbound_consent(
        _Session("granted"),
        uuid.uuid4(),
        customer_id=uuid.uuid4(),
        channel="email",
        purpose="marketing",
    )
    assert allowed.allowed and allowed.required

    refused = await evaluate_outbound_consent(
        _Session("revoked"),
        uuid.uuid4(),
        customer_id=uuid.uuid4(),
        channel="email",
        purpose="marketing",
    )
    assert not refused.allowed
    assert "revoked" in refused.reason


async def test_the_consent_lookup_is_tenant_scoped_in_sql():
    """Pin the WHERE clause itself — asserting the params dict would pass even
    if `tenant_id` were dropped from the query."""
    session = _Session(consent_status="granted")
    tenant_id = uuid.uuid4()

    await ConversationService.add_promotional_message(
        session, tenant_id, conversation_id=uuid.uuid4(), body=MARKETING
    )

    sql, params = _consent_calls(session)[0]
    assert "tenant_id = :tenant_id" in sql
    assert "customer_id = :customer_id" in sql
    assert "channel = :channel" in sql
    assert "purpose = :purpose" in sql
    assert params["tenant_id"] == tenant_id
    assert params["customer_id"] == session.conversation.customer_id
    assert params["channel"] == session.conversation.channel


# ------------------------------------------------------- the send path (DB) --


async def _customer_and_conversation(db: AsyncSession, tenant_id, *, channel="webchat"):
    from app.modules.customers.service import CustomerService

    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        channel=channel,
        external_id=f"wc-{uuid.uuid4().hex[:10]}",
        name="Consent Customer",
    )
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel=channel
    )
    return customer, conversation


async def _grant(
    db: AsyncSession,
    tenant_id,
    customer_id,
    *,
    channel="webchat",
    purpose="marketing",
    status="granted",
) -> object:
    from app.modules.privacy.models import Consent

    consent = Consent(
        tenant_id=tenant_id,
        customer_id=customer_id,
        channel=channel,
        purpose=purpose,
        status=status,
        source="test",
    )
    db.add(consent)
    await db.flush()
    return consent


async def test_a_promotional_send_without_consent_is_refused(db, tenant_ctx):
    _, conversation = await _customer_and_conversation(db, tenant_ctx.tenant_id)

    with pytest.raises(OutboundBlockedError) as exc:
        await ConversationService.add_promotional_message(
            db, tenant_ctx.tenant_id, conversation_id=conversation.id, body=MARKETING
        )
    assert "marketing" in str(exc.value)
    assert "webchat" in str(exc.value)


async def test_the_refused_promotional_message_is_not_persisted(db, tenant_ctx):
    from sqlalchemy import func, select

    from app.modules.conversations.models import Message

    _, conversation = await _customer_and_conversation(db, tenant_ctx.tenant_id)

    with pytest.raises(OutboundBlockedError):
        await ConversationService.add_promotional_message(
            db, tenant_ctx.tenant_id, conversation_id=conversation.id, body=MARKETING
        )

    count = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation.id)
        )
    ).scalar_one()
    assert count == 0, "a consent-blocked message was written anyway"


async def test_a_promotional_send_with_consent_granted_succeeds(db, tenant_ctx):
    customer, conversation = await _customer_and_conversation(db, tenant_ctx.tenant_id)
    await _grant(db, tenant_ctx.tenant_id, customer.id)

    message = await ConversationService.add_promotional_message(
        db, tenant_ctx.tenant_id, conversation_id=conversation.id, body=MARKETING
    )
    assert message.id is not None
    assert message.status == "queued"


async def test_a_revoked_consent_is_refused(db, tenant_ctx):
    customer, conversation = await _customer_and_conversation(db, tenant_ctx.tenant_id)
    consent = await _grant(db, tenant_ctx.tenant_id, customer.id)

    # Mirrors privacy/router.py revoke_consent: recorded, never deleted.
    consent.status = "revoked"
    consent.revoked_at = datetime.now(UTC)
    await db.flush()

    with pytest.raises(OutboundBlockedError):
        await ConversationService.add_promotional_message(
            db, tenant_ctx.tenant_id, conversation_id=conversation.id, body=MARKETING
        )


async def test_a_transactional_send_is_not_blocked_by_missing_marketing_consent(
    db, tenant_ctx
):
    """No consent of any kind exists — a shipping notice must still go out."""
    _, conversation = await _customer_and_conversation(db, tenant_ctx.tenant_id)

    message = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="agent",
        body=TRANSACTIONAL,
    )
    assert message.id is not None


async def test_consent_for_one_tenant_does_not_authorise_another(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    # Tenant A: consent granted, promotional send allowed.
    customer_a, conversation_a = await _customer_and_conversation(db, tenant_ctx.tenant_id)
    await _grant(db, tenant_ctx.tenant_id, customer_a.id)
    allowed = await ConversationService.add_promotional_message(
        db, tenant_ctx.tenant_id, conversation_id=conversation_a.id, body=MARKETING
    )
    assert allowed.id is not None

    # Tenant B: its own customer + conversation, but NO consent of its own.
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    _, conversation_b = await _customer_and_conversation(db, other.id)

    with pytest.raises(OutboundBlockedError):
        await ConversationService.add_promotional_message(
            db, other.id, conversation_id=conversation_b.id, body=MARKETING
        )

    await bind_tenant(db, tenant_ctx.tenant_id)
