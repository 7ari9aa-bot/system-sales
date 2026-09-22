"""§144/§175 — campaign execution is real: staged events, budgeted batches.

The campaign engine published through ``add_outbox_event(stream=..., ...)``
— a kwarg the writer never had (the stream is DERIVED from aggregate_type)
— and without ``await``. Python raises TypeError at the call, so starting a
campaign 500d and the §175 execution loop never ran. The AST guard below
pins the wiring contract for EVERY call site in app/, so the next
hand-merged call fails review-time, not production-time.

Runtime tests (DB) prove the run lifecycle actually stages envelopes the
workers can deserialize.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.events.schemas import DOMAIN_EVENT_TYPES
from app.modules.marketing.campaign import CampaignExecutionService, CampaignRunStatus
from app.modules.marketing.service import MarketingService
from app.modules.platform.models import OutboxEvent

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# ------------------------------------------------------- wiring guard ----


class _CallSite(ast.Call):
    """An add_outbox_event call annotated by the scan below."""

    awaited: bool
    file: str


@dataclass(slots=True)
class _CallSite:
    """One add_outbox_event call site, as the scan below finds it."""

    file: str
    lineno: int
    keywords: list[ast.keyword]
    awaited: bool


def _add_outbox_call_sites() -> list[_CallSite]:
    """Every add_outbox_event call in app/, marked awaited / not-awaited."""
    found: list[_CallSite] = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        awaited_calls = {
            id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Await)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "add_outbox_event"
            ):
                found.append(
                    _CallSite(
                        file=path.relative_to(APP_DIR).as_posix(),
                        lineno=node.lineno,
                        keywords=node.keywords,
                        awaited=id(node) in awaited_calls,
                    )
                )
    return found


def test_no_add_outbox_call_site_passes_a_stream_kwarg():
    """The stream is derived from aggregate_type ({aggregate}.events) —
    a hand-passed stream= means the call was written against a signature
    that does not exist (the campaign engine's bug)."""
    offenders = [
        f"{c.file}:{c.lineno}"
        for c in _add_outbox_call_sites()
        if any(kw.arg == "stream" for kw in c.keywords)
    ]
    assert offenders == [], f"add_outbox_event called with unknown stream= kwarg: {offenders}"


def test_every_add_outbox_call_is_awaited():
    """add_outbox_event is async — an unawaited call is a silent no-op
    (coroutine discarded) that breaks the event half of the transaction."""
    offenders = [
        f"{c.file}:{c.lineno}" for c in _add_outbox_call_sites() if not c.awaited
    ]
    assert offenders == [], f"add_outbox_event called without await: {offenders}"


def test_every_literal_event_type_is_registered():
    """An unregistered event_type fails the writer at runtime (§19 closed
    contract) — the call sites must be visible to the registration set."""
    literals: set[str] = set()
    for call in _add_outbox_call_sites():
        for kw in call.keywords:
            if kw.arg == "event_type" and isinstance(kw.value, ast.Constant):
                assert isinstance(kw.value.value, str)
                literals.add(kw.value.value)
    unregistered = sorted(literals - set(DOMAIN_EVENT_TYPES))
    assert unregistered == [], f"event types staged but never registered: {unregistered}"


# ------------------------------------------------------ run lifecycle ----


async def _campaign(db, tenant_id, name="Fairness Camp"):
    campaign = await MarketingService.create_campaign(
        db, tenant_id, name=name, provider="facebook"
    )
    campaign.status = "active"
    await db.flush()
    return campaign


async def _customer(db, tenant_id, phone: str):
    from app.modules.customers.service import CustomerService

    return await CustomerService.get_or_create_by_identity(
        db, tenant_id, channel="whatsapp", external_id=phone
    )


async def _grant_marketing(db, tenant_id, customer_id) -> None:
    from app.modules.privacy.models import Consent

    db.add(
        Consent(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel="whatsapp",
            purpose="marketing",
            status="granted",
            source="test",
        )
    )
    await db.flush()


async def _segment_all(db, tenant_id):
    from app.modules.segments.service import Segment

    segment = Segment(
        tenant_id=tenant_id,
        name="Everyone",
        definition={"field": "is_blocked", "op": "eq", "value": False},
        is_active=True,
    )
    db.add(segment)
    await db.flush()
    return segment


def _fake_redis(monkeypatch, tenant_id):
    """Pin the tenant's MESSAGES_OUTBOUND counter so the batch cap is real."""
    from fakeredis.aioredis import FakeRedis

    from app.core import fairness

    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(fairness, "get_redis", lambda: fake)
    return fake, fairness._budget_key(
        tenant_id, fairness.ResourceType.MESSAGES_OUTBOUND
    )


# -------------------------------------------------------- the worker pump --


async def test_pump_completes_a_run_without_an_audience(db, tenant_ctx):
    """The started event drives ONE batch; with no recipients the run ends
    and the completion event rides the same transaction."""
    from app.workers.campaign_worker import process_campaign_run_event

    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id)
    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id
    )

    outcome = await process_campaign_run_event(db, tenant_id, run.id)
    assert outcome == "completed"
    assert run.status == CampaignRunStatus.COMPLETED.value
    completed = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "campaign.run.completed"
            )
        )
    ).scalars().all()
    assert len(completed) == 1
    batched = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "campaign.run.batch"
            )
        )
    ).scalars().all()
    assert batched == []


async def test_pump_caps_a_batch_at_the_outbound_budget_and_queues_the_next(
    monkeypatch, db, tenant_ctx
):
    """§144 at the point of CONSUMPTION: remaining budget == 1 forces a batch
    of one, the sends are charged back to the budget, and the continuation is
    a paced event — never a loop hogging the worker."""
    from datetime import UTC, datetime

    from app.workers.campaign_worker import process_campaign_run_event

    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id)
    segment = await _segment_all(db, tenant_id)
    for phone in ("+10000000001", "+10000000002", "+10000000003"):
        customer = await _customer(db, tenant_id, phone)
        await _grant_marketing(db, tenant_id, customer.id)

    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id, segment_id=segment.id
    )

    # Counter one unit below the limit: exactly one message of remaining budget.
    limit = 10_000  # DEFAULT_DAILY_BUDGETS[MESSAGES_OUTBOUND]
    fake, key = _fake_redis(monkeypatch, tenant_id)
    await fake.set(key, limit - 1)

    outcome = await process_campaign_run_event(db, tenant_id, run.id)
    assert outcome == "batched"
    assert run.status == CampaignRunStatus.RUNNING.value
    # One recipient processed this batch — send or policy-refused, the cursor
    # advances exactly one and the run continues.
    assert run.sent_count + run.failed_count == 1
    # The budget was charged for what was ACTUALLY sent.
    counter_now = int(await fake.get(key))
    assert counter_now == (limit - 1) + run.sent_count

    batched = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "campaign.run.batch"
            )
        )
    ).scalars().all()
    assert len(batched) == 1
    assert batched[0].aggregate_id == run.id
    assert batched[0].stream == "campaign_run.events"
    # Pacing: the continuation is not instantly claimable.
    assert batched[0].not_before is not None
    assert batched[0].not_before > datetime.now(UTC)


async def test_pump_defers_when_the_outbound_budget_is_exhausted(
    monkeypatch, db, tenant_ctx
):
    """No remaining budget is NOT a failure: the event is deferred (§48-style,
    attempts untouched) and the run stays exactly where it was."""
    from app.workers.base import DeferredError
    from app.workers.campaign_worker import process_campaign_run_event

    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id)
    segment = await _segment_all(db, tenant_id)
    customer = await _customer(db, tenant_id, "+10000000009")
    await _grant_marketing(db, tenant_id, customer.id)
    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id, segment_id=segment.id
    )

    fake, key = _fake_redis(monkeypatch, tenant_id)
    await fake.set(key, 10_000)  # at the limit: zero remaining

    with pytest.raises(DeferredError):
        await process_campaign_run_event(db, tenant_id, run.id)
    assert run.status == CampaignRunStatus.RUNNING.value
    assert run.cursor is None


async def test_pump_defers_when_the_worker_time_budget_is_exhausted(
    monkeypatch, db, tenant_ctx
):
    """§144 tiering in practice: the BULK tier is gated by WORKER_SECONDS
    too — message budget intact, worker time spent → defer, do not starve."""
    from app.core import fairness
    from app.workers.base import DeferredError
    from app.workers.campaign_worker import process_campaign_run_event

    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id)
    segment = await _segment_all(db, tenant_id)
    customer = await _customer(db, tenant_id, "+10000000010")
    await _grant_marketing(db, tenant_id, customer.id)
    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id, segment_id=segment.id
    )

    fake, _ = _fake_redis(monkeypatch, tenant_id)
    worker_key = fairness._budget_key(
        tenant_id, fairness.ResourceType.WORKER_SECONDS
    )
    await fake.set(worker_key, 3_600)  # the full daily worker-time budget

    with pytest.raises(DeferredError):
        await process_campaign_run_event(db, tenant_id, run.id)
    assert run.status == CampaignRunStatus.RUNNING.value


async def test_pump_of_a_paused_run_is_a_noop(db, tenant_ctx):
    from app.workers.campaign_worker import process_campaign_run_event

    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id)
    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id
    )
    await CampaignExecutionService.pause(db, tenant_id, run.id)

    assert await process_campaign_run_event(db, tenant_id, run.id) == "not_running"
    batched = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "campaign.run.batch"
            )
        )
    ).scalars().all()
    assert batched == []


def test_campaign_pool_is_registered_in_the_worker_entrypoint():
    from app.workers.campaign_worker import CampaignWorker
    from app.workers.run import POOLS

    assert POOLS["campaigns"] is CampaignWorker
    assert CampaignWorker.stream == "campaign_run.events"


async def test_start_campaign_stages_a_run_started_envelope(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id)

    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id
    )

    row = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "campaign.run.started"
            )
        )
    ).scalar_one()
    assert row.aggregate_type == "campaign_run"
    assert row.stream == "campaign_run.events"
    assert row.aggregate_id == run.id
    assert row.meta["tenant_id"] == str(tenant_id)
    assert row.payload["campaign_id"] == str(campaign.id)


async def test_completing_an_empty_run_stages_the_completed_envelope(
    db, tenant_ctx
):
    """A run with no audience completes on its first batch and the completion
    is an event like everything else (§19: mutations, then outbox)."""
    tenant_id = tenant_ctx.tenant_id
    campaign = await _campaign(db, tenant_id, name="Empty Camp")
    run = await CampaignExecutionService.start_campaign(
        db, tenant_id, campaign_id=campaign.id
    )

    finished = await CampaignExecutionService.process_batch(
        db, tenant_id, run.id, batch_size=10
    )
    assert finished.status == CampaignRunStatus.COMPLETED.value

    row = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.payload["event_type"].astext == "campaign.run.completed"
            )
        )
    ).scalar_one()
    assert row.aggregate_id == run.id
    assert row.payload["sent"] == 0
    assert uuid.UUID(row.meta["tenant_id"]) == tenant_id
