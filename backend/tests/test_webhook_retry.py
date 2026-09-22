"""§24 — failed inbound webhook ingress rows are reprocessed, never lost.

The defect class this closes: ``webhook_events.processing_status`` only ever
moved processing → processed. A payload that failed mid-ingest left the row
stuck in ``processing`` forever (and the webhook request 500'd, inviting the
provider's retry storm). Now:

* the ingest block runs in a SAVEPOINT
  (``IngestService.process_webhook_event``) — a failure rolls back all of the
  block's writes and the router marks the row failed, records the error,
  increments attempts and still ACKs 200;
* the WebhookWorker (or the platform-admin retry endpoint, which stages a
  ``webhook.event.retry`` outbox event) re-runs the EXACT same block under
  the row's tenant — the per-message idempotency keys make the replay safe.

These tests drive the real Postgres fixtures and the real WhatsApp adapter;
the only monkeypatched seam is ``IngestService.ingest`` itself, so a
deterministic mid-flight failure can be simulated. The HTTP layer (signature
parsing, tenant resolution via the SECURITY DEFINER function) is out of scope
here — it is pinned by tests/test_gateway_security.py.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.errors import PermissionDeniedError, ValidationError
from app.core.events.writer import add_outbox_event
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter
from app.modules.conversations.models import Message
from app.modules.identity.deps import AuthedUser, TenantContext
from app.modules.platform.models import OutboxEvent, WebhookEvent
from app.modules.platform.router import admin_retry_webhook_event
from app.workers.platform_workers import retry_failed_webhook_events


def _wa_payload(*message_ids: str) -> dict:
    """A WhatsApp webhook envelope carrying the given text messages."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PNID123"},
                            "contacts": [
                                {"wa_id": "201234567890", "profile": {"name": "أحمد"}}
                            ],
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "201234567890",
                                    "type": "text",
                                    "text": {"body": f"رسالة {message_id}"},
                                }
                                for message_id in message_ids
                            ],
                        }
                    }
                ]
            }
        ]
    }


async def _ingress_row(
    db, tenant_id: uuid.UUID, payload: dict, *, status: str = "processing", attempts: int = 0
) -> WebhookEvent:
    row = WebhookEvent(
        provider="whatsapp",
        external_event_id=f"evt-{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id,
        signature_valid=True,
        payload=payload,
        processing_status=status,
        attempts=attempts,
    )
    db.add(row)
    await db.flush()
    return row


async def _reload(db, row_id: uuid.UUID) -> WebhookEvent:
    return (
        await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.id == row_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _inbound_count(db, tenant_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant_id, Message.direction == "inbound"
            )
        )
    ).scalar_one()


# ------------------------------------------------------- the ingest block --


async def test_processing_block_ingests_and_marks_the_row_processed(db, tenant_ctx):
    """Happy path: every parsed message is ingested and the ingress row lands
    on processed with its first attempt counted."""
    payload = _wa_payload("wamid.ok-1", "wamid.ok-2")
    row = await _ingress_row(db, tenant_ctx.tenant_id, payload)

    accepted = await IngestService.process_webhook_event(
        db,
        adapter=whatsapp_adapter,
        channel="whatsapp",
        tenant_id=tenant_ctx.tenant_id,
        event_id=row.id,
        payload=payload,
    )

    assert accepted == 2
    assert await _inbound_count(db, tenant_ctx.tenant_id) == 2
    stored = await _reload(db, row.id)
    assert stored.processing_status == "processed"
    assert stored.attempts == 1


async def test_a_mid_flight_failure_rolls_back_and_leaves_the_transaction_alive(
    db, tenant_ctx, monkeypatch
):
    """The second message explodes AFTER the first was written: the savepoint
    must roll the first write back, re-raise, and keep the session usable —
    that is what lets the router still ACK 200 after marking the row failed."""
    payload = _wa_payload("wamid.first", "wamid.second")
    row = await _ingress_row(db, tenant_ctx.tenant_id, payload)

    real_ingest = IngestService.ingest
    calls = {"n": 0}

    async def _second_message_explodes(session, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("second message exploded")
        return await real_ingest(session, **kwargs)

    monkeypatch.setattr(IngestService, "ingest", _second_message_explodes)

    with pytest.raises(RuntimeError):
        await IngestService.process_webhook_event(
            db,
            adapter=whatsapp_adapter,
            channel="whatsapp",
            tenant_id=tenant_ctx.tenant_id,
            event_id=row.id,
            payload=payload,
        )

    # §24 failure marking — same transaction, session never poisoned.
    await IngestService.mark_webhook_event_failed(
        db, row.id, RuntimeError("second message exploded")
    )

    assert await _inbound_count(db, tenant_ctx.tenant_id) == 0, (
        "the first message's writes survived the savepoint rollback"
    )
    stored = await _reload(db, row.id)
    assert stored.processing_status == "failed"
    assert stored.attempts == 1
    assert stored.last_error is not None
    assert "second message exploded" in stored.last_error


# --------------------------------------------------------- worker retries --


async def test_worker_retry_reingests_and_marks_the_row_processed(db, tenant_ctx):
    """A failed row re-runs the ingest path: the message lands (the idempotency
    key from the failed attempt rolled back, so nothing blocks it) and the row
    is processed with attempts incremented."""
    payload = _wa_payload("wamid.retry-ok")
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, payload, status="failed", attempts=1
    )

    handled = await retry_failed_webhook_events(db, tenant_ctx.tenant_id)

    assert handled == 1
    stored = await _reload(db, row.id)
    assert stored.processing_status == "processed"
    assert stored.attempts == 2
    assert await _inbound_count(db, tenant_ctx.tenant_id) == 1

    # The row is no longer failed — a second sweep must not touch it.
    assert await retry_failed_webhook_events(db, tenant_ctx.tenant_id) == 0


async def test_worker_retry_marks_a_persistent_failure_and_increments_attempts(
    db, tenant_ctx, monkeypatch
):
    """A payload that fails again stays failed — but the attempt is counted,
    so the retry budget burns down instead of looping forever."""

    async def _always_explodes(session, **kwargs):
        raise RuntimeError("still broken")

    monkeypatch.setattr(IngestService, "ingest", _always_explodes)

    payload = _wa_payload("wamid.still-bad")
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, payload, status="failed", attempts=1
    )

    handled = await retry_failed_webhook_events(db, tenant_ctx.tenant_id)

    assert handled == 1
    stored = await _reload(db, row.id)
    assert stored.processing_status == "failed"
    assert stored.attempts == 2
    assert "still broken" in (stored.last_error or "")


async def test_the_sweep_skips_rows_whose_budget_is_spent_but_an_explicit_retry_runs(
    db, tenant_ctx, monkeypatch
):
    """The sweep (no event id) never touches rows at/over the retry budget —
    permanently malformed payloads must not burn cycles. An EXPLICIT per-row
    retry (the admin endpoint's event) ignores the budget: a human decided."""
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(worker_max_attempts=1),
    )

    fresh = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.budget-ok"), status="failed",
        attempts=0,
    )
    spent = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.budget-spent"), status="failed",
        attempts=3,
    )

    # Sweep: only the row under the budget is handled.
    assert await retry_failed_webhook_events(db, tenant_ctx.tenant_id) == 1
    fresh_stored = await _reload(db, fresh.id)
    assert fresh_stored.processing_status == "processed"
    spent_stored = await _reload(db, spent.id)
    assert spent_stored.processing_status == "failed"
    assert spent_stored.attempts == 3

    # Explicit per-row retry: the spent-budget row is retried anyway.
    assert (
        await retry_failed_webhook_events(db, tenant_ctx.tenant_id, event_id=spent.id)
        == 1
    )
    spent_stored = await _reload(db, spent.id)
    assert spent_stored.processing_status == "processed"
    assert spent_stored.attempts == 4


# ---------------------------------------------- platform-admin retry API ---


def _admin_ctx(tenant_ctx, *, platform_admin: bool = True) -> TenantContext:
    """The admin plane gates on the GLOBAL ``is_platform_admin`` JWT claim
    (B2 review fix), not on tenant permission codes — fabricate that claim."""
    actor = AuthedUser(
        id=tenant_ctx.user.id,
        tenant_id=tenant_ctx.tenant_id,
        role_code=tenant_ctx.role.code,
        is_platform_admin=platform_admin,
    )
    return TenantContext(
        session=tenant_ctx.session,
        user=actor,
        tenant_id=tenant_ctx.tenant_id,
        role_code=tenant_ctx.role.code,
        permission_codes=set(),
    )


async def test_admin_retry_schedules_the_worker_event(db, tenant_ctx):
    """The endpoint does not process inline — it stages a webhook.event.retry
    outbox event for the WebhookWorker, carrying the row's tenant and id."""
    payload = _wa_payload("wamid.admin")
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, payload, status="failed", attempts=1
    )

    result = await admin_retry_webhook_event(_admin_ctx(tenant_ctx), row.id)

    assert result["retry"] == "scheduled"
    staged = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "webhook.event.retry")
        )
    ).scalar_one()
    assert staged.aggregate_id == row.id
    assert staged.payload["webhook_event_id"] == str(row.id)
    assert staged.meta["tenant_id"] == str(tenant_ctx.tenant_id)


async def test_admin_retry_requires_the_platform_admin_claim(db, tenant_ctx):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.noauth"), status="failed"
    )
    with pytest.raises(PermissionDeniedError):
        await admin_retry_webhook_event(_admin_ctx(tenant_ctx, platform_admin=False), row.id)


async def test_admin_retry_rejects_a_row_that_is_not_failed(db, tenant_ctx):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.processed"),
        status="processed", attempts=1,
    )
    with pytest.raises(ValidationError):
        await admin_retry_webhook_event(_admin_ctx(tenant_ctx), row.id)


async def test_a_webhook_event_retry_envelope_round_trips_through_the_writer(db, tenant_ctx):
    """The new event type must be a registered §19 envelope — an unregistered
    type makes add_outbox_event raise at the first real retry scheduling."""
    event = await add_outbox_event(
        db,
        aggregate_type="webhook",
        aggregate_id=uuid.uuid4(),
        event_type="webhook.event.retry",
        tenant_id=tenant_ctx.tenant_id,
        payload={"webhook_event_id": str(uuid.uuid4())},
    )
    assert event.payload["event_type"] == "webhook.event.retry"
    assert event.meta["outbox_id"] == str(event.id)
