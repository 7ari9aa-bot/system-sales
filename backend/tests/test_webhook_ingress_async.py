"""§22 — webhook ingress is async: verify → validate → dedupe → PERSIST RAW
→ ACK QUICKLY → process off the request path.

The route used to run the FULL ingest block inline (parse → customer →
conversation → messages → AI fan-out) before answering 200. A slow provider
call inside the block became a provider timeout → retry storm → duplicate
pressure on the very work that timed out (§22: "لا تعالج business workflow
الطويل داخل HTTP webhook request").

Now the route only does the durable part: the raw row lands and a
``webhook.ingest`` event is staged in the SAME transaction (the outbox —
no dual-write hole). The WebhookWorker re-runs the exact ingest block on
the queue; failures quarantine through the §24 budget as before.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter
from app.modules.conversations.models import Message
from app.modules.platform.models import OutboxEvent, WebhookEvent
from app.workers.platform_workers import ingest_queued_webhook_event
from tests.test_webhook_retry import _wa_payload


class _Request:
    """Minimal starlette Request surface the route uses."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.headers: dict[str, str] = {"x-signature-test": "1"}
        self.query_params: dict[str, str] = {}

    async def body(self) -> bytes:
        return self._raw


async def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    db,
    tenant_id: uuid.UUID | None,
    payload: dict,
    *,
    channel: str = "whatsapp",
) -> dict:
    """Drive the REAL route with the real WhatsApp payload shape; only the
    crypto signature and the SECURITY-DEFINER tenant lookup are stubbed."""
    import app.modules.conversations.router as cr

    async def _resolve(_session, _adapter, _key):
        return tenant_id

    monkeypatch.setattr(cr, "get_adapter", lambda _ch: whatsapp_adapter)
    monkeypatch.setattr(whatsapp_adapter, "check_signature", lambda _h, _b: True)
    monkeypatch.setattr(IngestService, "resolve_tenant", _resolve)
    raw = json.dumps(payload).encode()
    return await cr.channel_webhook(channel, _Request(raw), db)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ------------------------------------------------------------- the route ---


async def test_route_persists_and_queues_without_ingesting_inline(
    monkeypatch, db, tenant_ctx
):
    """The request path must NOT run the ingest block — persist + queue + ACK."""
    calls: list[Any] = []

    async def _never_inline(*args: Any, **kwargs: Any) -> int:
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(
        IngestService, "process_webhook_event", staticmethod(_never_inline)
    )

    payload = _wa_payload("wamid.async-1")
    response = await _call_route(monkeypatch, db, tenant_ctx.tenant_id, payload)

    assert response == {"ok": True, "queued": True}
    assert calls == [], "business ingest must not run inside the HTTP request"

    digest = _digest(json.dumps(payload).encode())
    row = (
        await db.execute(
            select(WebhookEvent).where(WebhookEvent.external_event_id == digest)
        )
    ).scalar_one()
    assert row.tenant_id == tenant_ctx.tenant_id
    assert row.processing_status == "pending"

    staged = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "webhook.ingest"
            )
        )
    ).scalar_one()
    assert staged.aggregate_id == row.id
    assert staged.meta["tenant_id"] == str(tenant_ctx.tenant_id)
    assert staged.payload["webhook_event_id"] == str(row.id)


async def test_a_replayed_delivery_is_acked_once_and_queued_once(
    monkeypatch, db, tenant_ctx
):
    payload = _wa_payload("wamid.async-dupe")
    first = await _call_route(monkeypatch, db, tenant_ctx.tenant_id, payload)
    second = await _call_route(monkeypatch, db, tenant_ctx.tenant_id, payload)

    assert first["queued"] is True
    assert second.get("duplicate") is True
    rows = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "webhook.ingest"
            )
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_unknown_tenant_still_acks_without_queuing(monkeypatch, db, tenant_ctx):
    """Unattributed deliveries are ACKed (no existence leak) — the raw row
    cannot be written under FORCE-RLS without a tenant; pinned behavior."""
    response = await _call_route(
        monkeypatch, db, None, _wa_payload("wamid.async-nope")
    )
    assert response == {"ok": True}


# ------------------------------------------------------------ the worker ---


async def test_worker_processes_a_queued_ingest_event(db, tenant_ctx):
    """The queued event runs the EXACT ingest block the old inline path ran."""
    row = WebhookEvent(
        provider="whatsapp",
        external_event_id=f"evt-{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_ctx.tenant_id,
        signature_valid=True,
        payload=_wa_payload("wamid.worker-1"),
        processing_status="pending",
    )
    db.add(row)
    await db.flush()

    handled = await ingest_queued_webhook_event(db, tenant_ctx.tenant_id, row.id)
    assert handled == 1
    stored = (
        await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.id == row.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert stored.processing_status == "processed"
    inbound = (
        await db.execute(
            select(Message).where(
                Message.tenant_id == tenant_ctx.tenant_id,
                Message.direction == "inbound",
            )
        )
    ).scalars().all()
    assert len(inbound) == 1


async def test_worker_quarantines_a_failing_ingest_under_the_budget(
    db, tenant_ctx, monkeypatch
):
    async def _explodes(session, **kwargs):
        raise RuntimeError("worker-side failure")

    monkeypatch.setattr(IngestService, "ingest", _explodes)

    row = WebhookEvent(
        provider="whatsapp",
        external_event_id=f"evt-{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_ctx.tenant_id,
        signature_valid=True,
        payload=_wa_payload("wamid.worker-bad"),
        processing_status="pending",
    )
    db.add(row)
    await db.flush()

    handled = await ingest_queued_webhook_event(db, tenant_ctx.tenant_id, row.id)
    assert handled == 1
    stored = (
        await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.id == row.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert stored.processing_status == "failed"
    assert stored.attempts == 1
    assert "worker-side failure" in (stored.last_error or "")
    # A failed queue pass does NOT re-raise — the §24 sweep owns the replay.


async def test_a_redelivered_event_for_a_processed_row_is_a_noop(db, tenant_ctx):
    """At-least-once delivery: the worker may see the same event twice (or
    after a crash-reclaim). An already-processed row must not double-ingest."""
    row = WebhookEvent(
        provider="whatsapp",
        external_event_id=f"evt-{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_ctx.tenant_id,
        signature_valid=True,
        payload=_wa_payload("wamid.worker-twice"),
        processing_status="processed",
        attempts=1,
    )
    db.add(row)
    await db.flush()

    assert await ingest_queued_webhook_event(db, tenant_ctx.tenant_id, row.id) == 0
    inbound = (
        await db.execute(
            select(Message.id).where(
                Message.tenant_id == tenant_ctx.tenant_id,
                Message.direction == "inbound",
            )
        )
    ).scalars().all()
    assert inbound == []
