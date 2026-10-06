"""AUTHORITY service (V12 Wave B) — Grants, Leases, and Budget reservations.

Enforces:
1. Invariant 10: Single-use, cryptographically verified authority lease with TTL <= 60s.
2. Invariant 11: CapabilityGrant scope and budget bounding.
3. Invariant 21: Command hash deterministic verification.
4. Invariant 22: Resource version verification (optimistic concurrency / state locking).
5. Invariant 62: Correctness SLO emissions.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.authority.models import (
    MAX_LEASE_TTL_SECONDS,
    AuthorityLease,
    AutonomyBudget,
    BudgetReservation,
    CapabilityGrant,
)
from app.modules.decisions.service import DecisionService


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuthorityService:
    """Core domain service for Capability Grants, Authority Leases, and Autonomy Budgets."""

    # ------------------------------------------------------------- Capability Grants

    @staticmethod
    async def issue_grant(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        tool_name: str,
        decision_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str = "system",
        scope: dict[str, Any] | None = None,
        max_budget: Decimal | None = None,
        currency: str = "USD",
        ttl_seconds: int = 3600,
    ) -> CapabilityGrant:
        if not tool_name or not tool_name.strip():
            raise ValidationError("tool_name is required for CapabilityGrant")

        if decision_id is not None:
            # Verify decision exists for this tenant via DecisionService (§8 boundary)
            await DecisionService.get(session, tenant_id, decision_id)

        now = datetime.now(UTC)
        grant = CapabilityGrant(
            tenant_id=tenant_id,
            decision_id=decision_id,
            actor_id=actor_id,
            actor_type=actor_type,
            tool_name=tool_name.strip(),
            scope=scope or {},
            max_budget=max_budget,
            currency=currency,
            status="ACTIVE",
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        session.add(grant)
        await session.flush()
        return grant

    @staticmethod
    async def get_grant(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        grant_id: uuid.UUID,
    ) -> CapabilityGrant:
        grant = await session.scalar(
            select(CapabilityGrant).where(
                CapabilityGrant.tenant_id == tenant_id,
                CapabilityGrant.grant_id == grant_id,
            )
        )
        if not grant:
            raise NotFoundError(f"CapabilityGrant {grant_id} not found")
        return grant

    @staticmethod
    async def list_grants(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        tool_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CapabilityGrant], int]:
        query = select(CapabilityGrant).where(CapabilityGrant.tenant_id == tenant_id)
        if tool_name:
            query = query.where(CapabilityGrant.tool_name == tool_name)
        if status:
            query = query.where(CapabilityGrant.status == status)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await session.scalar(count_query)) or 0

        grants = (
            await session.scalars(
                query.order_by(CapabilityGrant.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return list(grants), total

    @staticmethod
    async def revoke_grant(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        grant_id: uuid.UUID,
    ) -> CapabilityGrant:
        grant = await AuthorityService.get_grant(session, tenant_id, grant_id)
        grant.status = "REVOKED"
        grant.revoked_at = datetime.now(UTC)
        await session.flush()
        return grant

    # ------------------------------------------------------------- Authority Leases

    @staticmethod
    async def mint_lease(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        grant_id: uuid.UUID,
        decision_id: uuid.UUID,
        command_hash: str,
        expected_versions: dict[str, int] | None = None,
        ttl_seconds: int = 60,
        budget_amount: Decimal | None = None,
        budget_id: uuid.UUID | None = None,
    ) -> tuple[AuthorityLease, str]:
        """Mint a single-use Authority Lease with TTL <= 60s bound to a command_hash."""
        # 1. Enforce V12 TTL ceiling
        if ttl_seconds > MAX_LEASE_TTL_SECONDS or ttl_seconds < 1:
            raise ValidationError(
                f"Authority lease TTL must be between 1 and {MAX_LEASE_TTL_SECONDS}s, "
                f"got {ttl_seconds}"
            )

        if not command_hash or not command_hash.startswith("sha256:"):
            raise ValidationError("command_hash must be a valid 'sha256:<hex>' string")

        now = datetime.now(UTC)

        # 2. Verify Capability Grant
        grant = await AuthorityService.get_grant(session, tenant_id, grant_id)
        if grant.status != "ACTIVE":
            await metrics.record_authority_rejection()
            raise ConflictError(f"CapabilityGrant is not ACTIVE (status={grant.status})")
        if grant.expires_at <= now:
            grant.status = "EXPIRED"
            await session.flush()
            await metrics.record_authority_rejection()
            raise ConflictError("CapabilityGrant has expired")

        # 3. Verify Decision via DecisionService (§8: never import another module's .models)
        try:
            decision = await DecisionService.get(session, tenant_id, decision_id)
        except NotFoundError:
            await metrics.record_authority_rejection()
            raise NotFoundError(f"Decision {decision_id} not found") from None

        if decision.decision_status != "APPROVED":
            await metrics.record_authority_rejection()
            raise ConflictError(
                f"Decision must be in APPROVED state to mint authority lease "
                f"(current: {decision.decision_status})"
            )

        if decision.expires_at and decision.expires_at <= now:
            await DecisionService.mark_stale(session, tenant_id, decision_id)
            await metrics.record_decision_stale()
            await metrics.record_authority_rejection()
            raise ConflictError("Decision has expired past its TTL")

        # If decision already has command_hash pinned, ensure it matches
        if decision.command_hash and decision.command_hash != command_hash:
            await metrics.record_authority_rejection()
            raise ConflictError(
                f"command_hash {command_hash} does not match decision pinned "
                f"command_hash {decision.command_hash}"
            )

        # 4. Handle budget reservation if applicable
        reservation = None
        if budget_amount is not None and budget_amount > 0:
            if grant.max_budget is not None and budget_amount > grant.max_budget:
                await metrics.record_budget_fail()
                await metrics.record_authority_rejection()
                raise ConflictError(
                    f"Requested budget {budget_amount} exceeds grant max_budget {grant.max_budget}"
                )

            if budget_id is not None:
                reservation = await AuthorityService.reserve_budget(
                    session,
                    tenant_id,
                    budget_id=budget_id,
                    amount=budget_amount,
                    ttl_seconds=ttl_seconds,
                )

        # 5. Generate cryptographically secure token & nonce
        token_secret = secrets.token_urlsafe(32)
        lease_token = f"lease_tok_{token_secret}"
        token_hash = sha256_hex(lease_token)
        nonce = f"nonce_{uuid.uuid4().hex}"

        # 6. Create AuthorityLease row
        lease = AuthorityLease(
            tenant_id=tenant_id,
            grant_id=grant_id,
            decision_id=decision_id,
            lease_token_hash=token_hash,
            command_hash=command_hash,
            expected_versions=expected_versions or {},
            nonce=nonce,
            state="MINTED",
            ttl_seconds=ttl_seconds,
            expires_at=now + timedelta(seconds=ttl_seconds),
            reserved_budget=budget_amount,
        )
        session.add(lease)
        await session.flush()

        if reservation:
            reservation.lease_id = lease.lease_id
            await session.flush()

        return lease, lease_token

    @staticmethod
    async def get_lease_by_token(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        lease_token: str,
    ) -> AuthorityLease:
        token_hash = sha256_hex(lease_token)
        lease = await session.scalar(
            select(AuthorityLease).where(
                AuthorityLease.tenant_id == tenant_id,
                AuthorityLease.lease_token_hash == token_hash,
            )
        )
        if not lease:
            await metrics.record_authority_rejection()
            raise NotFoundError("Authority lease not found or invalid token")
        return lease

    @staticmethod
    async def list_leases(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuthorityLease], int]:
        query = select(AuthorityLease).where(AuthorityLease.tenant_id == tenant_id)
        if state:
            query = query.where(AuthorityLease.state == state)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await session.scalar(count_query)) or 0

        leases = (
            await session.scalars(
                query.order_by(AuthorityLease.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return list(leases), total

    @staticmethod
    async def revoke_lease(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        lease_id: uuid.UUID,
    ) -> AuthorityLease:
        lease = await session.scalar(
            select(AuthorityLease).where(
                AuthorityLease.tenant_id == tenant_id,
                AuthorityLease.lease_id == lease_id,
            )
        )
        if not lease:
            raise NotFoundError(f"AuthorityLease {lease_id} not found")
        lease.state = "REVOKED"
        await session.flush()
        return lease

    # ------------------------------------------------------------- Autonomy Budgets

    @staticmethod
    async def create_budget(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        name: str,
        total_limit: Decimal,
        currency: str = "USD",
        period: str = "DAILY",
        actor_id: uuid.UUID | None = None,
        parent_budget_id: uuid.UUID | None = None,
    ) -> AutonomyBudget:
        if total_limit <= 0:
            raise ValidationError("total_limit must be greater than zero")

        if parent_budget_id:
            parent = await session.scalar(
                select(AutonomyBudget).where(
                    AutonomyBudget.tenant_id == tenant_id,
                    AutonomyBudget.budget_id == parent_budget_id,
                ).with_for_update()
            )
            if not parent:
                raise NotFoundError(f"Parent budget {parent_budget_id} not found")
            available = parent.total_limit - parent.spent_amount - parent.reserved_amount
            if total_limit > available:
                await metrics.record_budget_fail()
                raise ConflictError(
                    f"Child budget limit ({total_limit}) exceeds parent available "
                    f"budget ({available})"
                )
            # Allocate the child's limit from the parent's available budget
            parent.spent_amount += total_limit

        budget = AutonomyBudget(
            tenant_id=tenant_id,
            actor_id=actor_id,
            parent_budget_id=parent_budget_id,
            name=name.strip(),
            period=period.upper(),
            currency=currency,
            total_limit=total_limit,
            spent_amount=Decimal("0.00"),
            reserved_amount=Decimal("0.00"),
        )
        session.add(budget)
        await session.flush()
        return budget

    @staticmethod
    async def get_budget(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        budget_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AutonomyBudget:
        stmt = select(AutonomyBudget).where(
            AutonomyBudget.tenant_id == tenant_id,
            AutonomyBudget.budget_id == budget_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
            
        budget = await session.scalar(stmt)
        if not budget:
            raise NotFoundError(f"AutonomyBudget {budget_id} not found")
        return budget

    @staticmethod
    async def list_budgets(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AutonomyBudget], int]:
        query = select(AutonomyBudget).where(AutonomyBudget.tenant_id == tenant_id)
        count_query = select(func.count()).select_from(query.subquery())
        total = (await session.scalar(count_query)) or 0

        budgets = (
            await session.scalars(
                query.order_by(AutonomyBudget.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return list(budgets), total

    @staticmethod
    async def reserve_budget(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        budget_id: uuid.UUID,
        amount: Decimal,
        lease_id: uuid.UUID | None = None,
        ttl_seconds: int = 60,
    ) -> BudgetReservation:
        budget = await AuthorityService.get_budget(session, tenant_id, budget_id, for_update=True)
        available = budget.total_limit - budget.spent_amount - budget.reserved_amount
        if amount > available:
            await metrics.record_budget_fail()
            raise ConflictError(
                f"Insufficient budget available: requested {amount}, available {available}"
            )

        budget.reserved_amount += amount
        now = datetime.now(UTC)
        reservation = BudgetReservation(
            tenant_id=tenant_id,
            budget_id=budget_id,
            lease_id=lease_id,
            amount=amount,
            status="RESERVED",
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        session.add(reservation)
        await session.flush()
        return reservation

    @staticmethod
    async def commit_reservation(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> None:
        reservation = await session.scalar(
            select(BudgetReservation).where(
                BudgetReservation.tenant_id == tenant_id,
                BudgetReservation.reservation_id == reservation_id,
            )
        )
        if not reservation or reservation.status != "RESERVED":
            return
        budget = await AuthorityService.get_budget(session, tenant_id, reservation.budget_id, for_update=True)
        budget.reserved_amount = max(Decimal("0.00"), budget.reserved_amount - reservation.amount)
        budget.spent_amount += reservation.amount
        reservation.status = "COMMITTED"
        await session.flush()

    @staticmethod
    async def release_reservation(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> None:
        reservation = await session.scalar(
            select(BudgetReservation).where(
                BudgetReservation.tenant_id == tenant_id,
                BudgetReservation.reservation_id == reservation_id,
            )
        )
        if not reservation or reservation.status != "RESERVED":
            return
        budget = await AuthorityService.get_budget(session, tenant_id, reservation.budget_id, for_update=True)
        budget.reserved_amount = max(Decimal("0.00"), budget.reserved_amount - reservation.amount)
        reservation.status = "RELEASED"
        await session.flush()
