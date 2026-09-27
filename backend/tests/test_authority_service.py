"""Tests for the Authority Service (V12 Wave B).

Covers:
- CapabilityGrant issuance, retrieval, revocation, listing, and validation
- Authority Lease minting, TTL enforcement, command_hash binding, single-use
- Autonomy Budget creation, parent-child slicing, headroom
- Budget Reservations: reserve, commit, release
- SLO metric emissions: budget_fail, authority_rejection
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa

from app.core.commands import command_hash as compute_command_hash
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.authority.models import (
    MAX_LEASE_TTL_SECONDS,
    AuthorityLease,
    AutonomyBudget,
    BudgetReservation,
    CapabilityGrant,
)
from app.modules.authority.service import AuthorityService
from app.modules.decisions.models import Decision
from app.modules.decisions.service import DecisionService


# ───────────────────────────────────── helpers ──────────────────────────────


async def _make_approved_decision(db, tenant_id: uuid.UUID) -> Decision:
    """Helper: create a PROPOSED decision, verify it, then approve it."""
    decision = await DecisionService.propose(
        db,
        tenant_id,
        action="test_action",
        risk_level="LOW",
        normalized_arguments={"qty": 1},
    )
    await DecisionService.verify(db, tenant_id, decision.decision_id)
    await DecisionService.approve(db, tenant_id, decision.decision_id)
    await db.refresh(decision)
    return decision


async def _make_grant(
    db,
    tenant_id: uuid.UUID,
    decision_id: uuid.UUID | None = None,
    tool_name: str = "create_order",
    max_budget: Decimal | None = Decimal("1000.00"),
    ttl_seconds: int = 3600,
) -> CapabilityGrant:
    return await AuthorityService.issue_grant(
        db,
        tenant_id,
        tool_name=tool_name,
        decision_id=decision_id,
        max_budget=max_budget,
        ttl_seconds=ttl_seconds,
    )


async def _make_budget(
    db,
    tenant_id: uuid.UUID,
    total_limit: Decimal = Decimal("5000.00"),
    name: str = "test-budget",
) -> AutonomyBudget:
    return await AuthorityService.create_budget(
        db,
        tenant_id,
        name=name,
        total_limit=total_limit,
    )


# ═══════════════════════════ CapabilityGrant tests ══════════════════════════


class TestCapabilityGrants:
    async def test_issue_grant_basic(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        grant = await _make_grant(db, tid)
        assert grant.grant_id is not None
        assert grant.tenant_id == tid
        assert grant.tool_name == "create_order"
        assert grant.status == "ACTIVE"
        assert grant.max_budget == Decimal("1000.00")

    async def test_issue_grant_empty_tool_name_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(ValidationError):
            await AuthorityService.issue_grant(db, tid, tool_name="  ")

    async def test_issue_grant_with_decision(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid, decision_id=decision.decision_id)
        assert grant.decision_id == decision.decision_id

    async def test_issue_grant_nonexistent_decision_404(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        fake_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            await _make_grant(db, tid, decision_id=fake_id)

    async def test_get_grant(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        grant = await _make_grant(db, tid)
        fetched = await AuthorityService.get_grant(db, tid, grant.grant_id)
        assert fetched.grant_id == grant.grant_id

    async def test_get_grant_not_found(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(NotFoundError):
            await AuthorityService.get_grant(db, tid, uuid.uuid4())

    async def test_list_grants_filter_by_tool(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        await _make_grant(db, tid, tool_name="create_order")
        await _make_grant(db, tid, tool_name="update_price")
        items, total = await AuthorityService.list_grants(db, tid, tool_name="update_price")
        assert total == 1
        assert items[0].tool_name == "update_price"

    async def test_list_grants_filter_by_status(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        g1 = await _make_grant(db, tid)
        await _make_grant(db, tid, tool_name="other_tool")
        await AuthorityService.revoke_grant(db, tid, g1.grant_id)
        items, total = await AuthorityService.list_grants(db, tid, status="REVOKED")
        assert total == 1
        assert items[0].grant_id == g1.grant_id

    async def test_revoke_grant(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        grant = await _make_grant(db, tid)
        revoked = await AuthorityService.revoke_grant(db, tid, grant.grant_id)
        assert revoked.status == "REVOKED"
        assert revoked.revoked_at is not None

    async def test_grant_expiry_enforced_via_ttl(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        grant = await _make_grant(db, tid, ttl_seconds=1)
        assert grant.expires_at <= datetime.now(UTC) + timedelta(seconds=2)


# ═══════════════════════════ AuthorityLease tests ═══════════════════════════


class TestAuthorityLeases:
    async def test_mint_lease_basic(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        lease, token = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
        )
        assert lease.state == "MINTED"
        assert lease.command_hash == cmd_hash
        assert token.startswith("lease_tok_")
        assert lease.ttl_seconds == 60

    async def test_mint_lease_ttl_above_60_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        with pytest.raises(ValidationError, match="TTL"):
            await AuthorityService.mint_lease(
                db, tid,
                grant_id=grant.grant_id,
                decision_id=decision.decision_id,
                command_hash=cmd_hash,
                ttl_seconds=61,
            )

    async def test_mint_lease_ttl_zero_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        with pytest.raises(ValidationError, match="TTL"):
            await AuthorityService.mint_lease(
                db, tid,
                grant_id=grant.grant_id,
                decision_id=decision.decision_id,
                command_hash=cmd_hash,
                ttl_seconds=0,
            )

    async def test_mint_lease_bad_command_hash_format(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        with pytest.raises(ValidationError, match="command_hash"):
            await AuthorityService.mint_lease(
                db, tid,
                grant_id=grant.grant_id,
                decision_id=decision.decision_id,
                command_hash="not-a-sha256-hash",
            )

    async def test_mint_lease_revoked_grant_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        await AuthorityService.revoke_grant(db, tid, grant.grant_id)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        with pytest.raises(ConflictError, match="ACTIVE"):
            await AuthorityService.mint_lease(
                db, tid,
                grant_id=grant.grant_id,
                decision_id=decision.decision_id,
                command_hash=cmd_hash,
            )

    async def test_mint_lease_unapproved_decision_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await DecisionService.propose(
            db, tid, action="test", risk_level="LOW",
        )
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        with pytest.raises(ConflictError, match="APPROVED"):
            await AuthorityService.mint_lease(
                db, tid,
                grant_id=grant.grant_id,
                decision_id=decision.decision_id,
                command_hash=cmd_hash,
            )

    async def test_mint_lease_budget_exceeds_grant_max(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid, max_budget=Decimal("100.00"))
        budget = await _make_budget(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        with pytest.raises(ConflictError, match="exceeds"):
            await AuthorityService.mint_lease(
                db, tid,
                grant_id=grant.grant_id,
                decision_id=decision.decision_id,
                command_hash=cmd_hash,
                budget_amount=Decimal("200.00"),
                budget_id=budget.budget_id,
            )

    async def test_get_lease_by_token(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        lease, token = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
        )
        fetched = await AuthorityService.get_lease_by_token(db, tid, token)
        assert fetched.lease_id == lease.lease_id

    async def test_get_lease_invalid_token_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(NotFoundError):
            await AuthorityService.get_lease_by_token(db, tid, "bad_token")

    async def test_list_leases_filter_by_state(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        lease, _ = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
        )
        items, total = await AuthorityService.list_leases(db, tid, state="MINTED")
        assert total >= 1
        assert all(l.state == "MINTED" for l in items)

    async def test_revoke_lease(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        decision = await _make_approved_decision(db, tid)
        grant = await _make_grant(db, tid)
        cmd_hash = compute_command_hash(
            str(tid), action="test", resource={}, arguments={}, purpose="test",
        )
        lease, _ = await AuthorityService.mint_lease(
            db, tid,
            grant_id=grant.grant_id,
            decision_id=decision.decision_id,
            command_hash=cmd_hash,
        )
        revoked = await AuthorityService.revoke_lease(db, tid, lease.lease_id)
        assert revoked.state == "REVOKED"


# ═══════════════════════════ AutonomyBudget tests ═══════════════════════════


class TestAutonomyBudgets:
    async def test_create_budget_basic(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid)
        assert budget.budget_id is not None
        assert budget.total_limit == Decimal("5000.00")
        assert budget.spent_amount == Decimal("0.00")
        assert budget.reserved_amount == Decimal("0.00")

    async def test_create_budget_zero_limit_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(ValidationError, match="greater than zero"):
            await AuthorityService.create_budget(
                db, tid, name="bad", total_limit=Decimal("0"),
            )

    async def test_create_budget_negative_limit_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(ValidationError, match="greater than zero"):
            await AuthorityService.create_budget(
                db, tid, name="bad", total_limit=Decimal("-100"),
            )

    async def test_create_child_budget_within_parent(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        parent = await _make_budget(db, tid, total_limit=Decimal("10000.00"), name="parent")
        child = await AuthorityService.create_budget(
            db, tid,
            name="child",
            total_limit=Decimal("5000.00"),
            parent_budget_id=parent.budget_id,
        )
        assert child.parent_budget_id == parent.budget_id
        assert child.total_limit == Decimal("5000.00")

    async def test_create_child_budget_exceeds_parent_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        parent = await _make_budget(db, tid, total_limit=Decimal("1000.00"), name="parent")
        with pytest.raises(ConflictError, match="exceeds"):
            await AuthorityService.create_budget(
                db, tid,
                name="child",
                total_limit=Decimal("2000.00"),
                parent_budget_id=parent.budget_id,
            )

    async def test_create_child_nonexistent_parent_rejected(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        with pytest.raises(NotFoundError):
            await AuthorityService.create_budget(
                db, tid,
                name="orphan",
                total_limit=Decimal("100.00"),
                parent_budget_id=uuid.uuid4(),
            )

    async def test_get_budget(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid)
        fetched = await AuthorityService.get_budget(db, tid, budget.budget_id)
        assert fetched.budget_id == budget.budget_id

    async def test_list_budgets(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        await _make_budget(db, tid, name="b1")
        await _make_budget(db, tid, name="b2")
        items, total = await AuthorityService.list_budgets(db, tid)
        assert total >= 2


# ═══════════════════════════ BudgetReservation tests ════════════════════════


class TestBudgetReservations:
    async def test_reserve_budget_basic(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("1000.00"))
        reservation = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("200.00"),
        )
        assert reservation.status == "RESERVED"
        assert reservation.amount == Decimal("200.00")
        await db.refresh(budget)
        assert budget.reserved_amount == Decimal("200.00")

    async def test_reserve_budget_exceeds_available(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("500.00"))
        with pytest.raises(ConflictError, match="Insufficient"):
            await AuthorityService.reserve_budget(
                db, tid, budget_id=budget.budget_id, amount=Decimal("600.00"),
            )

    async def test_commit_reservation(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("1000.00"))
        reservation = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("300.00"),
        )
        await AuthorityService.commit_reservation(db, tid, reservation.reservation_id)
        await db.refresh(budget)
        await db.refresh(reservation)
        assert reservation.status == "COMMITTED"
        assert budget.spent_amount == Decimal("300.00")
        assert budget.reserved_amount == Decimal("0.00")

    async def test_release_reservation(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("1000.00"))
        reservation = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("400.00"),
        )
        await AuthorityService.release_reservation(db, tid, reservation.reservation_id)
        await db.refresh(budget)
        await db.refresh(reservation)
        assert reservation.status == "RELEASED"
        assert budget.reserved_amount == Decimal("0.00")

    async def test_commit_idempotent_after_committed(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("1000.00"))
        reservation = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("100.00"),
        )
        await AuthorityService.commit_reservation(db, tid, reservation.reservation_id)
        # Second commit should be a no-op
        await AuthorityService.commit_reservation(db, tid, reservation.reservation_id)
        await db.refresh(budget)
        assert budget.spent_amount == Decimal("100.00")

    async def test_release_idempotent_after_released(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("1000.00"))
        reservation = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("100.00"),
        )
        await AuthorityService.release_reservation(db, tid, reservation.reservation_id)
        # Second release should be a no-op
        await AuthorityService.release_reservation(db, tid, reservation.reservation_id)
        await db.refresh(budget)
        assert budget.reserved_amount == Decimal("0.00")

    async def test_multiple_reservations_headroom(self, tenant_ctx):
        db, tid = tenant_ctx.session, tenant_ctx.tenant_id
        budget = await _make_budget(db, tid, total_limit=Decimal("1000.00"))
        r1 = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("400.00"),
        )
        r2 = await AuthorityService.reserve_budget(
            db, tid, budget_id=budget.budget_id, amount=Decimal("400.00"),
        )
        # Third reservation that exceeds remaining headroom
        with pytest.raises(ConflictError, match="Insufficient"):
            await AuthorityService.reserve_budget(
                db, tid, budget_id=budget.budget_id, amount=Decimal("300.00"),
            )
        await db.refresh(budget)
        assert budget.reserved_amount == Decimal("800.00")
