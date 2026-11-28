"""A message Meta refused for a temporary reason is tried again; nothing else ever is.

DB-backed: the worker counts refusals in ``delivery_attempts`` and flips the message back to
``queued``. The two things that must never happen are a second send of a message that may have
reached the customer (UNKNOWN), and a retry that the consumer inbox then swallows silently.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from app.applications.apparel.modules.conversations.models import Message
from app.applications.apparel.modules.conversations.service import ConversationService
from app.applications.apparel.modules.customers.models import Customer, CustomerIdentity
from app.modules.platform.models import DeliveryAttempt
from app.workers import message_worker as mw
from app.workers.base import DeferredError
from app.workers.message_worker import MessageWorker
from app.workers.outbound_retry import RETRY_DELAYS_SECONDS

RATE_LIMITED = 'whatsapp send failed: 429 {"error": {"message": "slow down", "code": 130429}}'
WINDOW_CLOSED = 'whatsapp send failed: 400 {"error": {"message": "re-engage", "code": 131047}}'
TOKEN_DEAD = 'whatsapp send failed: 401 {"error": {"message": "expired", "code": 190}}'


class _Session:
    """The test's session, but `begin()` is a savepoint: the fixture's own transaction is already
    open, and the worker opens (and commits) one per phase exactly as it does in production."""

    def __init__(self, session):
        self._s = session

    def begin(self):
        return self._s.begin_nested()

    def __getattr__(self, name):
        return getattr(self._s, name)


class _Ctx:
    """`SessionLocal()` stand-in that hands the test's own session to the worker."""

    def __init__(self, session):
        self._s = _Session(session)

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def worker(db, monkeypatch):
    monkeypatch.setattr(mw, "SessionLocal", lambda: _Ctx(db))
    return MessageWorker(bus=MagicMock())


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        adapter=SimpleNamespace(name="whatsapp"),
        outbound=SimpleNamespace(customer_ref="c-1", template_name=None, media_url=None),
    )


async def _sending_message(db, tenant_id, *, status: str = "sending") -> Message:
    customer = Customer(tenant_id=tenant_id, name="Waiting Customer")
    db.add(customer)
    await db.flush()
    db.add(
        CustomerIdentity(
            tenant_id=tenant_id,
            customer_id=customer.id,
            channel="webchat",
            external_id=f"visitor-{customer.id}",
        )
    )
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="ai",
        body="رد على العميل",
    )
    message.status = status
    await db.flush()
    return message


async def _refusals(db, tenant_id, message_id) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(DeliveryAttempt)
            .where(
                DeliveryAttempt.tenant_id == tenant_id,
                DeliveryAttempt.message_id == message_id,
                DeliveryAttempt.outcome == "failed",
            )
        )
    ).scalar_one()


async def _refuse(worker, db, tenant_id, message, error=RATE_LIMITED):
    """One refused send, as phase 2 would report it. Returns the deferral, or None."""
    try:
        await worker._defer_if_transient(tenant_id, message.id, _plan(), error)
    except DeferredError as exc:
        return exc
    return None


async def test_a_rate_limited_send_goes_back_to_the_queue_and_is_deferred(db, tenant_ctx, worker):
    tenant_id = tenant_ctx.tenant_id
    message = await _sending_message(db, tenant_id)

    deferral = await _refuse(worker, db, tenant_id, message)

    assert deferral is not None
    assert deferral.delay_seconds == RETRY_DELAYS_SECONDS[0]
    await db.refresh(message)
    assert message.status == "queued", "phase 1 only claims a QUEUED message, so it must be queued"
    assert "retrying" in (message.error or "")
    assert await _refusals(db, tenant_id, message.id) == 1


async def test_the_delay_grows_with_each_refusal_then_it_gives_up(db, tenant_ctx, worker):
    tenant_id = tenant_ctx.tenant_id
    message = await _sending_message(db, tenant_id)

    delays = []
    for _ in RETRY_DELAYS_SECONDS:
        message.status = "sending"  # phase 1 claims it again before every attempt
        await db.flush()
        deferral = await _refuse(worker, db, tenant_id, message)
        delays.append(deferral.delay_seconds)
    assert delays == list(RETRY_DELAYS_SECONDS)

    message.status = "sending"
    await db.flush()
    assert await _refuse(worker, db, tenant_id, message) is None, "the fourth refusal is final"
    await db.refresh(message)
    assert message.status == "sending", "left for the normal FAILED path, which the owner hears"
    assert await _refusals(db, tenant_id, message.id) == len(RETRY_DELAYS_SECONDS)


@pytest.mark.parametrize("error", [WINDOW_CLOSED, TOKEN_DEAD, "boom", None])
async def test_a_refusal_that_waiting_cannot_fix_is_never_retried(db, tenant_ctx, worker, error):
    tenant_id = tenant_ctx.tenant_id
    message = await _sending_message(db, tenant_id)

    assert await _refuse(worker, db, tenant_id, message, error) is None
    await db.refresh(message)
    assert message.status == "sending"
    assert await _refusals(db, tenant_id, message.id) == 0


async def test_a_message_that_is_not_in_flight_is_left_alone(db, tenant_ctx, worker):
    """A webhook may already have moved it on (delivered/read): never drag it back to queued."""
    tenant_id = tenant_ctx.tenant_id
    message = await _sending_message(db, tenant_id, status="delivered")

    assert await _refuse(worker, db, tenant_id, message) is None
    await db.refresh(message)
    assert message.status == "delivered"
    assert await _refusals(db, tenant_id, message.id) == 0


async def test_the_retry_writes_no_processed_event_so_the_inbox_cannot_swallow_it(
    db, tenant_ctx, worker
):
    """`ProcessedEvent` means the effect happened. The redelivered event keeps its outbox id, so
    a row written for a deferred attempt would make the retry exit silently, message queued."""
    from app.modules.platform.models import ProcessedEvent

    tenant_id = tenant_ctx.tenant_id
    message = await _sending_message(db, tenant_id)
    before = (await db.execute(select(func.count()).select_from(ProcessedEvent))).scalar_one()

    assert await _refuse(worker, db, tenant_id, message) is not None

    after = (await db.execute(select(func.count()).select_from(ProcessedEvent))).scalar_one()
    assert after == before


async def test_the_refusal_is_audited_with_the_wait_that_follows(db, tenant_ctx, worker):
    tenant_id = tenant_ctx.tenant_id
    message = await _sending_message(db, tenant_id)
    await _refuse(worker, db, tenant_id, message)

    attempt = (
        await db.execute(select(DeliveryAttempt).where(DeliveryAttempt.message_id == message.id))
    ).scalar_one()
    assert attempt.outcome == "failed"
    assert attempt.request_payload["will_retry_in_seconds"] == RETRY_DELAYS_SECONDS[0]
    assert "130429" in (attempt.error or "")


# ---- the whole `_deliver`, with a stand-in provider ---------------------------------------------


class _Provider:
    """A channel adapter whose answers the test scripts: a provider id, or an exception."""

    name = "webchat"

    def __init__(self, *answers):
        self._answers = list(answers)
        self.sends = 0

    async def send(self, credentials, outbound):
        self.sends += 1
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _envelope(tenant_id, message):
    from app.core.events.schemas import EventEnvelope

    return EventEnvelope(
        type="message.outbound",
        tenant_id=tenant_id,
        aggregate_type="message",
        aggregate_id=message.id,
        payload={"event_type": "message.outbound", "message_id": str(message.id)},
        meta={"outbox_id": str(message.id)},
    )


async def _queued_message(db, tenant_id) -> Message:
    return await _sending_message(db, tenant_id, status="queued")


async def test_a_rate_limited_send_is_deferred_not_failed_and_the_next_attempt_sends_it(
    db, tenant_ctx, worker, monkeypatch
):
    from app.modules.platform.models import ProcessedEvent

    tenant_id = tenant_ctx.tenant_id
    message = await _queued_message(db, tenant_id)
    provider = _Provider(RuntimeError(RATE_LIMITED), "provider-msg-1")
    monkeypatch.setattr(mw, "get_adapter", lambda channel: provider)
    envelope = _envelope(tenant_id, message)

    with pytest.raises(DeferredError) as deferral:
        await worker._deliver(envelope)
    assert deferral.value.delay_seconds == RETRY_DELAYS_SECONDS[0]
    await db.refresh(message)
    assert message.status == "queued"
    inbox = (
        await db.execute(
            select(func.count())
            .select_from(ProcessedEvent)
            .where(ProcessedEvent.event_id == message.id)
        )
    ).scalar_one()
    assert inbox == 0, "the redelivered event would exit silently and the message never go out"

    await worker._deliver(envelope)  # the deferred event arrives again
    await db.refresh(message)
    assert provider.sends == 2
    assert message.status == "sent"
    assert message.error is None, "a delivered message must not keep the retry note"


async def test_an_unknown_outcome_is_never_resent(db, tenant_ctx, worker, monkeypatch):
    """A timeout may already have reached the customer. It is not deferred, and the redelivery
    dead-letters for reconciliation instead of sending the message a second time."""
    from httpx import ReadTimeout

    from app.workers.base import PermanentError, RetryableError

    tenant_id = tenant_ctx.tenant_id
    message = await _queued_message(db, tenant_id)
    provider = _Provider(ReadTimeout("timed out"), "must-never-be-used")
    monkeypatch.setattr(mw, "get_adapter", lambda channel: provider)
    envelope = _envelope(tenant_id, message)

    with pytest.raises(RetryableError):  # the runtime's own retry, as before this change
        await worker._deliver(envelope)
    await db.refresh(message)
    assert message.status == "unknown"

    with pytest.raises((PermanentError, RetryableError)):
        await worker._deliver(envelope)
    assert provider.sends == 1, "a possibly-delivered message was sent again"


async def test_a_refusal_that_waiting_cannot_fix_fails_at_once(db, tenant_ctx, worker, monkeypatch):
    from app.workers.base import PermanentError

    tenant_id = tenant_ctx.tenant_id
    message = await _queued_message(db, tenant_id)
    provider = _Provider(RuntimeError(TOKEN_DEAD), "must-never-be-used")
    monkeypatch.setattr(mw, "get_adapter", lambda channel: provider)

    with pytest.raises(PermanentError):
        await worker._deliver(_envelope(tenant_id, message))
    await db.refresh(message)
    assert message.status == "failed"
    assert provider.sends == 1


async def test_after_the_last_retry_the_message_fails_and_the_owner_is_told(
    db, tenant_ctx, worker, monkeypatch
):
    from app.modules.notifications.models import Notification
    from app.workers.base import PermanentError

    tenant_id = tenant_ctx.tenant_id
    message = await _queued_message(db, tenant_id)
    provider = _Provider(*[RuntimeError(RATE_LIMITED)] * (len(RETRY_DELAYS_SECONDS) + 1))
    monkeypatch.setattr(mw, "get_adapter", lambda channel: provider)
    envelope = _envelope(tenant_id, message)

    for _ in RETRY_DELAYS_SECONDS:
        with pytest.raises(DeferredError):
            await worker._deliver(envelope)
    with pytest.raises(PermanentError):
        await worker._deliver(envelope)

    await db.refresh(message)
    assert message.status == "failed"
    assert provider.sends == len(RETRY_DELAYS_SECONDS) + 1
    bells = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.tenant_id == tenant_id, Notification.kind == "delivery_failed")
        )
    ).scalar_one()
    assert bells == 1, "a message that never went out must still reach the owner's bell"
