"""The webhook_delivery_sweep recurring job — durable backstop for stuck rows.

The delivery worker is crash-safe through the stream's PEL reclaim, but a row
whose stream event is gone (Redis flush, maxlen trim, DLQ'd entry) would sit
queued/failed forever: its retry schedule lives on the ROW, so something
durable must read it back. The sweep re-enqueues through the outbox — the same
route the worker's own failure path uses — and dies rows past the attempts
budget instead of looping.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.platform.models import OutboxEvent, WebhookDelivery, WebhookEndpoint
from app.workers import scheduler_worker as sw


async def _delivery(
    db,
    tenant_id: uuid.UUID,
    *,
    status: str,
    attempts: int = 0,
    stale_minutes: int = 30,
    next_retry_at: datetime | None = None,
) -> WebhookDelivery:
    endpoint = WebhookEndpoint(
        tenant_id=tenant_id,
        url="https://example.test/hook",
        secret="s" * 32,
        events=["order.paid"],
    )
    db.add(endpoint)
    await db.flush()
    row = WebhookDelivery(
        tenant_id=tenant_id,
        webhook_id=endpoint.id,
        event_name="order.paid",
        payload={"order_id": "x"},
        status=status,
        attempts=attempts,
        next_retry_at=next_retry_at,
        created_at=datetime.now(UTC) - timedelta(minutes=stale_minutes),
        updated_at=datetime.now(UTC) - timedelta(minutes=stale_minutes),
    )
    db.add(row)
    await db.flush()
    return row


def test_the_sweep_is_a_registered_recurring_job() -> None:
    assert "webhook_delivery_sweep" in sw.RECURRING_JOBS
    assert "webhook_delivery_sweep" in sw._HANDLERS


async def test_the_sweep_requeues_a_stuck_row_through_the_outbox(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    stuck = await _delivery(db, tenant_id, status="queued", stale_minutes=30)

    result = await sw._handle_webhook_delivery_sweep(db, tenant_id, {})

    assert result == {"scanned": 1, "requeued": 1}
    await db.flush()
    refreshed = (
        await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == stuck.id))
    ).scalar_one()
    assert refreshed.status == "queued", "the sweep must not touch the status it re-queues"
    # The re-enqueue rode the outbox — the relay will re-fire webhook.deliver.
    # The outbox is tenant-blind — the envelope's payload carries the
    # tenant_id; match on aggregate + payload instead.
    outbox = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "webhook",
                    OutboxEvent.aggregate_id == stuck.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbox) == 1
    # payload is a flat dict with event_type first (workers route on it);
    # the delivery id rides beside it.
    assert outbox[0].payload.get("event_type") == "webhook.deliver"
    assert outbox[0].payload.get("delivery_id") == str(stuck.id)
    assert outbox[0].meta.get("tenant_id") == str(tenant_id)


async def test_the_sweep_kills_a_row_past_its_attempts_budget(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    exhausted = await _delivery(db, tenant_id, status="failed", attempts=99, stale_minutes=30)

    await sw._handle_webhook_delivery_sweep(db, tenant_id, {})

    refreshed = (
        await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == exhausted.id))
    ).scalar_one()
    assert refreshed.status == "dead"
    assert "attempts budget" in (refreshed.last_error or "")


async def test_the_sweep_ignores_fresh_rows_and_terminal_rows(db, tenant_ctx) -> None:
    """A row a live worker may be holding (updated seconds ago) and terminal
    rows are invisible to the sweep — the 5-minute grace prevents racing the
    three delivery phases."""
    tenant_id = tenant_ctx.tenant_id
    await _delivery(db, tenant_id, status="queued", stale_minutes=0)
    await _delivery(db, tenant_id, status="delivered", stale_minutes=30)
    await _delivery(db, tenant_id, status="dead", stale_minutes=30)

    result = await sw._handle_webhook_delivery_sweep(db, tenant_id, {})

    assert result == {"scanned": 0, "requeued": 0}


async def test_the_sweep_honors_a_future_retry_schedule(db, tenant_ctx) -> None:
    """next_retry_at in the future means the live path already scheduled it —
    the sweep waits for the schedule to lapse rather than double-firing."""
    tenant_id = tenant_ctx.tenant_id
    scheduled = await _delivery(
        db,
        tenant_id,
        status="failed",
        stale_minutes=30,
        next_retry_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    result = await sw._handle_webhook_delivery_sweep(db, tenant_id, {})

    assert result == {"scanned": 0, "requeued": 0}
    refreshed = (
        await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == scheduled.id))
    ).scalar_one()
    assert refreshed.status == "failed"


@pytest.fixture(autouse=True)
def _isolate_outbox(monkeypatch):
    """The sweep writes outbox rows in the caller's transaction — no relay."""
    yield
