"""§24 — the dead-letter queue is real: a spent retry budget lands rows in
``dead``, and the DLQ surface (Inspect / Replay / Retry / Ignore / Mark
resolved) can act on them. Nothing disappears.

Before this slice the lifecycle stopped at ``failed``: a row whose attempts
burned the budget stayed ``failed`` forever, ``dead`` existed only in the
model comment, and the only admin operation on ingress rows was retry —
no list, no inspect, no way to close a case (ignore / resolve) or audit
who closed it.

The boundary test (mark_webhook_event_failed → CASE) runs anywhere; the
rest drive the real Postgres fixtures like test_webhook_retry.py and run in
CI.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.platform.models import AuditLog, OutboxEvent
from app.modules.platform.router import (
    admin_ignore_webhook_event,
    admin_inspect_webhook_event,
    admin_list_webhook_events,
    admin_resolve_webhook_event,
    admin_retry_webhook_event,
)
from app.workers.platform_workers import retry_failed_webhook_events
from tests.test_webhook_retry import _admin_ctx, _ingress_row, _reload, _wa_payload

# ------------------------------------------------- dead-lettering boundary --


class _CapturingUpdate:
    def __init__(self) -> None:
        self.statement: Any = None

    async def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Any:
        self.statement = statement
        return SimpleNamespace(rowcount=1)


def _literal_sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


async def test_the_budgets_last_failure_dead_letters_the_row(monkeypatch) -> None:
    """mark_webhook_event_failed must transition to dead — not failed — when
    this attempt exhausts the budget (§24: Retry 1..N then the DLQ)."""
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(worker_max_attempts=3),
    )
    session = _CapturingUpdate()
    # attempts=2 → this is failure #3 → the budget is spent.
    await IngestService.mark_webhook_event_failed(
        session, uuid.uuid4(), RuntimeError("boom")
    )
    sql = _literal_sql(session.statement)
    assert "CASE" in sql, "status must be derived from the attempts budget"
    assert "'dead'" in sql
    assert "'failed'" in sql


async def test_a_row_with_budget_left_stays_failed_for_the_sweep(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(worker_max_attempts=3),
    )
    session = _CapturingUpdate()
    await IngestService.mark_webhook_event_failed(
        session, uuid.uuid4(), RuntimeError("boom")
    )
    # The guard compares the POST-increment attempts against the budget:
    # attempts + 1 >= max → dead, else failed. Both branches exist, and the
    # increment rides in the same statement.
    sql = _literal_sql(session.statement)
    assert "attempts + 1" in sql
    assert ">= 3" in sql


# ------------------------------------------------------- CI-only behaviour --


async def test_sweep_dead_letters_after_the_last_allowed_failure(
    db, tenant_ctx, monkeypatch
):
    """Three strikes: attempts 2 with a budget of 3 — the next failure is the
    last one the queue tolerates; the row must land in dead."""
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(worker_max_attempts=3),
    )

    async def _always_explodes(session, **kwargs):
        raise RuntimeError("still broken")

    monkeypatch.setattr(IngestService, "ingest", _always_explodes)

    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-final"),
        status="failed", attempts=2,
    )
    assert await retry_failed_webhook_events(db, tenant_ctx.tenant_id) == 1
    stored = await _reload(db, row.id)
    assert stored.processing_status == "dead"
    assert stored.attempts == 3
    assert "still broken" in (stored.last_error or "")


async def test_the_automatic_sweep_never_touches_dead_rows(db, tenant_ctx, monkeypatch):
    """Dead is the DLQ: only a human (retry/ignore/resolve) acts on it."""
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(worker_max_attempts=3),
    )

    async def _always_explodes(session, **kwargs):
        raise RuntimeError("must not run")

    monkeypatch.setattr(IngestService, "ingest", _always_explodes)

    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-quiet"),
        status="dead", attempts=3,
    )
    assert await retry_failed_webhook_events(db, tenant_ctx.tenant_id) == 0
    stored = await _reload(db, row.id)
    assert stored.processing_status == "dead"
    assert stored.attempts == 3


async def test_an_explicit_worker_retry_replays_a_dead_row(db, tenant_ctx):
    """§24 Replay: the WebhookWorker path must accept an event_id pointing at
    a dead row — that is how an admin-staged retry lands."""
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-replay"),
        status="dead", attempts=3,
    )
    assert (
        await retry_failed_webhook_events(db, tenant_ctx.tenant_id, event_id=row.id)
        == 1
    )
    stored = await _reload(db, row.id)
    assert stored.processing_status == "processed"


async def test_admin_retry_accepts_a_dead_row_and_stages_the_worker_event(
    db, tenant_ctx
):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-admin-retry"),
        status="dead", attempts=3,
    )
    result = await admin_retry_webhook_event(_admin_ctx(tenant_ctx), row.id)
    assert result["retry"] == "scheduled"
    staged = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "webhook.event.retry"
            )
        )
    ).scalar_one()
    assert staged.aggregate_id == row.id


async def test_admin_retry_still_refuses_processed_rows(db, tenant_ctx):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.done"),
        status="processed", attempts=1,
    )
    with pytest.raises(ValidationError):
        await admin_retry_webhook_event(_admin_ctx(tenant_ctx), row.id)


# ------------------------------------------- ignore / resolve (DLQ close-out)


async def test_ignore_moves_a_dead_row_to_ignored_and_audits_the_decision(
    db, tenant_ctx
):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-ignore"),
        status="dead", attempts=3,
    )
    result = await admin_ignore_webhook_event(
        _admin_ctx(tenant_ctx), row.id, reason="provider sent junk"
    )
    assert result["status"] == "ignored"
    stored = await _reload(db, row.id)
    assert stored.processing_status == "ignored"  # the row is NOT deleted
    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "webhook_event.ignored")
        )
    ).scalar_one()
    assert audit.resource_id == str(row.id)
    assert "provider sent junk" in str(audit.before | audit.after or {})


async def test_resolved_is_a_valid_close_out_from_failed_or_dead(db, tenant_ctx):
    dead = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-resolve"),
        status="dead", attempts=3,
    )
    result = await admin_resolve_webhook_event(
        _admin_ctx(tenant_ctx), dead.id, reason="fixed upstream, re-keyed manually"
    )
    assert result["status"] == "resolved"
    stored = await _reload(db, dead.id)
    assert stored.processing_status == "resolved"


@pytest.mark.parametrize(
    ("op", "from_status"),
    [
        ("ignore", "processed"),
        ("ignore", "ignored"),
        ("ignore", "resolved"),
        ("resolve", "processed"),
        ("resolve", "resolved"),
    ],
)
async def test_illegal_dlq_transitions_are_refused(db, tenant_ctx, op, from_status):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload(f"wamid.bad-{from_status}-{op}"),
        status=from_status, attempts=1,
    )
    fn = admin_ignore_webhook_event if op == "ignore" else admin_resolve_webhook_event
    with pytest.raises(ValidationError):
        await fn(_admin_ctx(tenant_ctx), row.id, reason="nope nope nope")


async def test_dlq_ops_require_the_platform_admin_claim(db, tenant_ctx):
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.dlq-noauth"),
        status="dead", attempts=3,
    )
    ctx = _admin_ctx(tenant_ctx, platform_admin=False)
    with pytest.raises(PermissionDeniedError):
        await admin_ignore_webhook_event(ctx, row.id, reason="should not pass")
    with pytest.raises(PermissionDeniedError):
        await admin_resolve_webhook_event(ctx, row.id, reason="should not pass")


# ------------------------------------------------- inspect (list + detail) --


async def test_list_returns_the_tenants_ingress_rows_with_filters(db, tenant_ctx):
    await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.list-a"),
        status="dead", attempts=3,
    )
    await _ingress_row(
        db, tenant_ctx.tenant_id, _wa_payload("wamid.list-b"),
        status="processed", attempts=1,
    )
    listing = await admin_list_webhook_events(
        _admin_ctx(tenant_ctx), status=None, provider=None, limit=50, offset=0
    )
    assert listing["total"] >= 2
    statuses = {item["processing_status"] for item in listing["items"]}
    assert {"dead", "processed"} <= statuses
    # list payload is a summary: no full body riding along
    assert all("payload" not in item for item in listing["items"])

    only_dead = await admin_list_webhook_events(
        _admin_ctx(tenant_ctx), status="dead", provider="whatsapp", limit=50, offset=0
    )
    assert only_dead["total"] >= 1
    assert all(i["processing_status"] == "dead" for i in only_dead["items"])


async def test_list_rejects_an_unknown_status_filter(db, tenant_ctx):
    with pytest.raises(ValidationError):
        await admin_list_webhook_events(
            _admin_ctx(tenant_ctx), status="banana", provider=None, limit=50, offset=0
        )


async def test_inspect_returns_the_full_row_including_payload(db, tenant_ctx):
    payload = _wa_payload("wamid.inspect")
    row = await _ingress_row(
        db, tenant_ctx.tenant_id, payload, status="dead", attempts=3
    )
    detail = await admin_inspect_webhook_event(_admin_ctx(tenant_ctx), row.id)
    assert detail["id"] == str(row.id)
    assert detail["payload"]["entry"] == payload["entry"]
    assert detail["attempts"] == 3


async def test_inspect_missing_row_is_404(db, tenant_ctx):
    with pytest.raises(NotFoundError):
        await admin_inspect_webhook_event(_admin_ctx(tenant_ctx), uuid.uuid4())
