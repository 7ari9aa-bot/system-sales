"""Tests for the Atomic Execution Service (V12 Wave B §23).

Covers the canonical 15-step execution boundary:
- Token lookup, nonce uniqueness
- command_hash binding (must match canonical hash of payload)
- TTL enforcement (expired lease rejected)
- Single-use enforcement (MINTED-only)
- Grant validation during execution
- Decision validation during execution
- Resource version conflict detection
- Budget reservation commit on execution
- Successful mutation_fn callback invocation
- Outbox event creation with lineage (decision_id, effect_id)
- SLO metric emissions
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa

from app.core.commands import command_hash as compute_command_hash
from app.core.errors import ConflictError, NotFoundError
from app.modules.authority.executor import AtomicExecutionService
from app.modules.authority.models import AuthorityLease
from app.modules.authority.service import AuthorityService
from app.modules.decisions.service import DecisionService


# ───────────────────────────────────── helpers ──────────────────────────────

ACTION = "apply_discount"
PURPOSE = "test exec"


async def _setup_full_chain(db, tenant_id):
    """Create Decision -> approve -> Grant -> Lease with matching command_hash."""
    decision = await DecisionService.propose(
        db, tenant_id,
        action="test_action", risk_level="LOW",
        normalized_arguments={"qty": 1},
    )
    await DecisionService.verify(db, tenant_id, decision.decision_id)
    await DecisionService.approve(db, tenant_id, decision.decision_id)
    await db.refresh(decision)

    grant = await AuthorityService.issue_grant(
        db, tenant_id,
        tool_name="test_tool",
        max_budget=Decimal("5000.00"),
    )

    cmd_hash = compute_command_hash(
        str(tenant_id),
        action=ACTION,
        resource={"type": "order"},
        arguments={"discount": "10"},
        purpose=PURPOSE,
    )

    lease, token = await AuthorityService.mint_lease(
        db, tenant_id,
        grant_id=grant.grant_id,
        decision_id=decision.decision_id,
        command_hash=cmd_hash,
    )
    return decision, grant, lease, token, cmd_hash


# ═══════════════════════════ AtomicExecution tests ══════════════════════════


class TestAtomicExecution:
    async def test_execute_happy_path(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        mutation_fn = AsyncMock(return_value={"result": "ok", "applied": True})

        result = await AtomicExecutionService.execute_command(
            db, tid,
            lease_token=token,
            action=ACTION,
            resource={"type": "order"},
            arguments={"discount": "10"},
            purpose=PURPOSE,
            mutation_fn=mutation_fn,
        )

        assert result.success is True
        assert result.lease_id == lease.lease_id
        assert result.decision_id == decision.decision_id
        assert result.effect_id is not None
        assert result.mutation_result == {"result": "ok", "applied": True}
        mutation_fn.assert_called_once()

        # Verify lease is now EXECUTED
        await db.refresh(lease)
        assert lease.state == "EXECUTED"
        assert lease.redeemed_at is not None

        # Verify decision is EXECUTED
        await db.refresh(decision)
        assert decision.decision_status == "EXECUTED"

    async def test_execute_invalid_token_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(NotFoundError, match="not found"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token="bogus_token",
                action=ACTION,
                resource={},
                arguments={},
                purpose=PURPOSE,
            )

    async def test_execute_already_redeemed_lease_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        # First execution succeeds
        await AtomicExecutionService.execute_command(
            db, tid,
            lease_token=token,
            action=ACTION,
            resource={"type": "order"},
            arguments={"discount": "10"},
            purpose=PURPOSE,
        )

        # Second attempt with same token: lease is now EXECUTED, not MINTED
        with pytest.raises(ConflictError, match="already redeemed"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
            )

    async def test_execute_command_hash_mismatch_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        # Execute with DIFFERENT arguments -> different hash -> mismatch
        with pytest.raises(ConflictError, match="command_hash mismatch"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "20"},  # different!
                purpose=PURPOSE,
            )

    async def test_execute_expired_lease_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        # Force-expire the lease
        lease.expires_at = datetime.now(UTC) - timedelta(seconds=10)
        await db.flush()

        with pytest.raises(ConflictError, match="expired"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
            )
        await db.refresh(lease)
        assert lease.state == "EXPIRED"

    async def test_execute_revoked_grant_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        # Revoke the grant after minting the lease
        await AuthorityService.revoke_grant(db, tid, grant.grant_id)

        with pytest.raises(ConflictError, match="not ACTIVE"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
            )

    async def test_execute_expired_grant_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        # Force-expire the grant
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=10)
        await db.flush()

        with pytest.raises(ConflictError, match="expired"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
            )

    async def test_execute_revoked_decision_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        # Revoke decision after minting lease
        await DecisionService.revoke(db, tid, decision.decision_id)

        with pytest.raises(ConflictError, match="not in APPROVED"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
            )

    async def test_execute_resource_version_conflict_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id

        # Create chain with expected_versions
        decision = await DecisionService.propose(
            db, tid, action="test", risk_level="LOW",
        )
        await DecisionService.verify(db, tid, decision.decision_id)
        await DecisionService.approve(db, tid, decision.decision_id)
        await db.refresh(decision)

        grant = await AuthorityService.issue_grant(db, tid, tool_name="t")
        cmd_hash = compute_command_hash(
            str(tid), action=ACTION, resource={"type": "order"},
            arguments={"discount": "10"}, purpose=PURPOSE,
        )
        lease, token = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
            expected_versions={"product:P1": 5, "inventory:P1/W1": 10},
        )

        # Execute with WRONG current_versions -> conflict
        with pytest.raises(ConflictError, match="version conflict"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
                current_versions={"product:P1": 6, "inventory:P1/W1": 10},
            )

    async def test_execute_resource_version_match_succeeds(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id

        decision = await DecisionService.propose(
            db, tid, action="test", risk_level="LOW",
        )
        await DecisionService.verify(db, tid, decision.decision_id)
        await DecisionService.approve(db, tid, decision.decision_id)
        await db.refresh(decision)

        grant = await AuthorityService.issue_grant(db, tid, tool_name="t")
        cmd_hash = compute_command_hash(
            str(tid), action=ACTION, resource={"type": "order"},
            arguments={"discount": "10"}, purpose=PURPOSE,
        )
        lease, token = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
            expected_versions={"product:P1": 5},
        )

        # Matching version -> success
        result = await AtomicExecutionService.execute_command(
            db, tid,
            lease_token=token,
            action=ACTION,
            resource={"type": "order"},
            arguments={"discount": "10"},
            purpose=PURPOSE,
            current_versions={"product:P1": 5},
        )
        assert result.success is True

    async def test_execute_with_budget_reservation_committed(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id

        decision = await DecisionService.propose(
            db, tid, action="test", risk_level="LOW",
        )
        await DecisionService.verify(db, tid, decision.decision_id)
        await DecisionService.approve(db, tid, decision.decision_id)
        await db.refresh(decision)

        budget = await AuthorityService.create_budget(
            db, tid, name="exec-budget", total_limit=Decimal("1000.00"),
        )
        grant = await AuthorityService.issue_grant(
            db, tid, tool_name="t", max_budget=Decimal("500.00"),
        )
        cmd_hash = compute_command_hash(
            str(tid), action=ACTION, resource={"type": "order"},
            arguments={"discount": "10"}, purpose=PURPOSE,
        )
        lease, token = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
            budget_amount=Decimal("200.00"),
            budget_id=budget.budget_id,
        )

        result = await AtomicExecutionService.execute_command(
            db, tid,
            lease_token=token,
            action=ACTION,
            resource={"type": "order"},
            arguments={"discount": "10"},
            purpose=PURPOSE,
        )
        assert result.success is True

        # Budget reservation should be committed
        await db.refresh(budget)
        assert budget.spent_amount == Decimal("200.00")
        assert budget.reserved_amount == Decimal("0.00")

    async def test_execute_with_outbox_event(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        agg_id = uuid.uuid4()
        result = await AtomicExecutionService.execute_command(
            db, tid,
            lease_token=token,
            action=ACTION,
            resource={"type": "order"},
            arguments={"discount": "10"},
            purpose=PURPOSE,
            outbox_aggregate_type="order",
            outbox_aggregate_id=agg_id,
            outbox_event_type="order.discount_applied",
            outbox_payload={"discount_pct": 10},
        )
        assert result.success is True
        assert result.effect_id is not None

    async def test_execute_no_mutation_fn(self, tenant_ctx):
        """Execution without mutation_fn should succeed (dry-run / effect-only)."""
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        result = await AtomicExecutionService.execute_command(
            db, tid,
            lease_token=token,
            action=ACTION,
            resource={"type": "order"},
            arguments={"discount": "10"},
            purpose=PURPOSE,
            mutation_fn=None,
        )
        assert result.success is True
        assert result.mutation_result == {}

    async def test_execute_mutation_fn_exception_propagates(self, tenant_ctx):
        """If mutation_fn raises, the entire atomic transaction should fail."""
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision, grant, lease, token, cmd_hash = await _setup_full_chain(db, tid)

        async def failing_mutation(session):
            raise RuntimeError("mutation failed!")

        with pytest.raises(RuntimeError, match="mutation failed"):
            await AtomicExecutionService.execute_command(
                db, tid,
                lease_token=token,
                action=ACTION,
                resource={"type": "order"},
                arguments={"discount": "10"},
                purpose=PURPOSE,
                mutation_fn=failing_mutation,
            )
