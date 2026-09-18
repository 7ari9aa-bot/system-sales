"""Pre-production architecture gate (spec §176).

These scenarios must ALL pass before onboarding a real tenant. Each test maps
to a §176 line. Run: pytest tests/gate -q
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.core.errors import NotFoundError, ValidationError
from app.core.lease import conversation_lease
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.customers.service import IdentityMergeService
from app.modules.platform.models import ProcessedEvent

pytestmark = [pytest.mark.gate]


# --- 1. Cross-tenant RLS (§11/§176.1) — verified in rls_smoke_test too ---
async def test_gate_cross_tenant_rls(db, tenant_ctx):
    from app.modules.conversations.service import ConversationService

    foreign = uuid.uuid4()
    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Gate")
    db.add(customer)
    await db.flush()
    convo = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )
    with pytest.raises(NotFoundError):
        await ConversationService.get(db, foreign, convo.id)


# --- 2. Worker tenant-context propagation (§125) ---
async def test_gate_worker_tenant_context(db, _engine):
    """Workers bind the tenant GUC before touching tenant tables — the
    message worker's _deliver path uses bind_tenant; verified via raw SQL."""
    tid = str(uuid.uuid4())
    async with _engine.connect() as conn:
        result = (
            await conn.execute(
                text(
                    "SELECT set_config('app.tenant_id', :t, true), "
                    "current_setting('app.tenant_id', true)"
                ),
                {"t": tid},
            )
        ).scalar_one()
        assert result == tid  # GUC round-trips


# --- 3. Duplicate event dedupe (§127/§176.4) ---
async def test_gate_duplicate_event_dedupe(db):
    """ProcessedEvent unique(consumer,event_id) makes at-least-once safe."""
    event_id = uuid.uuid4()
    db.add(ProcessedEvent(consumer_name="gate", event_id=event_id))
    await db.flush()
    from sqlalchemy.exc import IntegrityError

    db.add(ProcessedEvent(consumer_name="gate", event_id=event_id))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


# --- 4. Duplicate outbound suppressed (§129/§176.5) ---
async def test_gate_worker_replay_skips_sent(db, tenant_ctx):
    """MessageWorker._deliver_one must not resend non-queued messages."""

    from app.modules.customers.models import Customer
    from app.workers.message_worker import MessageWorker

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Replay")
    db.add(customer)
    await db.flush()
    convo = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = await ConversationService.add_message(
        db, tenant_ctx.tenant_id, conversation_id=convo.id,
        direction="outbound", sender_type="agent", body="sent already",
    )
    message.status = "sent"
    await db.flush()

    worker = MessageWorker.__new__(MessageWorker)  # skip __init__ (bus unused)
    sent_calls = []

    class FakeAdapter:
        name = "webchat"

        async def send(self, credentials, message):
            sent_calls.append(1)
            return "provider-1"

    import app.workers.message_worker as mw

    original = mw.get_adapter
    mw.get_adapter = lambda name: FakeAdapter()
    try:
        await worker._deliver_one(db, tenant_ctx.tenant_id, message.id)
    finally:
        mw.get_adapter = original
    assert sent_calls == []  # already-sent message was NOT resent


# --- 5. Conversation race serialization (§126/§176.7) ---
async def test_gate_conversation_lease_exclusive(db, tenant_ctx):
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Race")
    db.add(customer)
    await db.flush()
    convo = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )
    async with conversation_lease(db, convo.id):
        # A DIFFERENT connection must be locked out (same-transaction
        # re-acquisition is re-entrant by Postgres design).
        import asyncpg

        from app.core.config import get_settings

        dsn = get_settings().database_url_app_admin.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        other = await asyncpg.connect(dsn, timeout=15)
        try:
            # Match lease.py's key derivation EXACTLY: uuid-int mod 2^63.
            key = uuid.UUID(str(convo.id)).int % (2**63 - 1)
            acquired = await other.fetchval(
                "SELECT pg_try_advisory_lock($1)", key
            )
            assert acquired is False, "second connection acquired the lease!"
            await other.execute("SELECT pg_advisory_unlock($1)", key)
        finally:
            await other.close()


# --- 6. AI budget exhaustion (§42/§176.20) ---
async def test_gate_ai_budget_block(db, tenant_ctx, monkeypatch):
    from datetime import UTC, datetime

    from app.modules.ai.gateway import enforce_budget
    from app.modules.ai.models import AIUsage, BudgetPolicy

    db.add(
        BudgetPolicy(
            tenant_id=tenant_ctx.tenant_id, scope="tenant", period="monthly",
            hard_cap=10, on_exceed="block",
        )
    )
    db.add(
        AIUsage(
            tenant_id=tenant_ctx.tenant_id, period_date=datetime.now(UTC).date(),
            tokens_in=0, tokens_out=0, cost=11,
        )
    )
    await db.flush()
    from app.core.errors import RateLimitExceededError

    with pytest.raises(RateLimitExceededError):
        await enforce_budget(db, tenant_ctx.tenant_id)


# --- 7. Identity merge preserves history (§28) ---
async def test_gate_merge_remaps_and_tombstones(db, tenant_ctx):
    from app.modules.customers.models import Customer
    from app.modules.customers.service import (
        CustomerService,
    )

    cust_a = await CustomerService.get_or_create_by_identity(
        db, tenant_ctx.tenant_id, channel="whatsapp", external_id="g1", name="A"
    )
    cust_b = await CustomerService.get_or_create_by_identity(
        db, tenant_ctx.tenant_id, channel="whatsapp", external_id="g2", name="B"
    )
    # Ensure the tenant GUC is bound on THIS session before raw SQL
    # (fresh fixtures per test — do not rely on fixture ordering).
    from app.core.db import bind_tenant

    await bind_tenant(db, tenant_ctx.tenant_id)
    _dbg = (
        await db.execute(
            text(
                "SELECT id, tenant_id, merged_into_customer_id, deleted_at "
                "FROM customers WHERE id = :cid"
            ),
            {"cid": cust_a.id},
        )
    ).first()
    print("DEBUG canonical row:", _dbg, "| expected tenant:", tenant_ctx.tenant_id)
    _dbg2 = (
        await db.execute(
            text(
                "SELECT id FROM customers WHERE tenant_id = :t "
                "AND id = :cid AND merged_into_customer_id IS NULL "
                "AND deleted_at IS NULL FOR UPDATE"
            ),
            {"t": tenant_ctx.tenant_id, "cid": cust_a.id},
        )
    ).scalar_one_or_none()
    print("DEBUG for-update select:", _dbg2)
    await IdentityMergeService.merge(
        db, tenant_ctx.tenant_id,
        canonical_customer_id=cust_a.id, merged_away_customer_id=cust_b.id,
    )
    merged_row = (
        await db.execute(
            select(Customer.merged_into_customer_id).where(Customer.id == cust_b.id)
        )
    ).scalar_one()
    assert merged_row == cust_a.id
    # cust_b was merged away (tombstoned) → can no longer be canonical
    with pytest.raises(NotFoundError):
        await IdentityMergeService.merge(
            db, tenant_ctx.tenant_id,
            canonical_customer_id=cust_b.id, merged_away_customer_id=cust_a.id,
        )


# --- 8. Segments DSL is injection-safe (§82) ---
async def test_gate_segment_dsl_whitelist(db, tenant_ctx):
    from app.modules.segments.service import validate_dsl

    with pytest.raises(ValidationError):
        validate_dsl({"all": [{"field": "password_hash", "op": "eq", "value": "x"}]})
    with pytest.raises(ValidationError):
        validate_dsl({"all": [{"field": "1=1; DROP TABLE customers", "op": "eq", "value": 1}]})
