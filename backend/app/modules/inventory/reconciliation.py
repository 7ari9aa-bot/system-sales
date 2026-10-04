"""Inventory reconciliation (§188) — the ledger and the projection are
compared on a schedule, and every discrepancy becomes an explicit finding.

Two checks:

``chain``      — every movement row replays from its predecessor:
                 prev + in → +qty, out → −qty, adjust → qty (absolute),
                 hold/release → unchanged. A row whose replayed position
                 differs from its own ``balance_after`` is forged or
                 corrupted, and is reported with its id.
``projection`` — every balance must equal the last ledger position of its
                 (warehouse, variant) pair; a non-zero balance with no
                 ledger rows at all is drift by definition.

Nothing here CORRECTS anything. A finding is operator work: resolve_finding
moves OPEN → RESOLVED and records who resolved it, what they saw, and why.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    InventoryReconciliationFinding,
)

_RUN_BATCH_LIMIT = 500


class InventoryReconciliationService:
    @staticmethod
    async def reconcile_tenant(session: AsyncSession, tenant_id: UUID) -> dict:
        """Compare ledger and projection for one tenant; insert new findings.

        Idempotent per run: a (check, warehouse, variant, movement) key that
        already has an OPEN finding is not duplicated. The caller owns the
        transaction.
        """
        findings: list[dict] = []

        # ---- chain check: replay each row from its predecessor ------------
        ordered = (
            select(
                InventoryMovement.id.label("id"),
                InventoryMovement.warehouse_id.label("warehouse_id"),
                InventoryMovement.variant_id.label("variant_id"),
                InventoryMovement.direction.label("direction"),
                InventoryMovement.quantity.label("quantity"),
                InventoryMovement.balance_after.label("balance_after"),
                func.lag(InventoryMovement.balance_after)
                .over(
                    partition_by=[
                        InventoryMovement.warehouse_id,
                        InventoryMovement.variant_id,
                    ],
                    order_by=[
                        InventoryMovement.created_at.asc(),
                        InventoryMovement.ledger_seq.asc(),
                    ],
                )
                .label("prev_after"),
            )
            .where(InventoryMovement.tenant_id == tenant_id)
            .subquery()
        )
        replayed = case(
            (
                ordered.c.direction == "in",
                func.coalesce(ordered.c.prev_after, 0) + ordered.c.quantity,
            ),
            (
                ordered.c.direction == "out",
                func.coalesce(ordered.c.prev_after, 0) - ordered.c.quantity,
            ),
            (ordered.c.direction == "adjust", ordered.c.quantity),
            else_=func.coalesce(ordered.c.prev_after, 0),
        )
        chain_rows = (
            await session.execute(
                select(
                    ordered.c.id,
                    ordered.c.warehouse_id,
                    ordered.c.variant_id,
                    replayed.label("expected"),
                    ordered.c.balance_after.label("actual"),
                ).where(replayed != ordered.c.balance_after)
            )
        ).all()
        for row in chain_rows:
            findings.append(
                {
                    "check": "chain",
                    "warehouse_id": row.warehouse_id,
                    "variant_id": row.variant_id,
                    "movement_id": row.id,
                    "expected": row.expected,
                    "actual": row.actual,
                }
            )

        # ---- projection check: balance == last ledger position -------------
        ranked = (
            select(
                InventoryMovement.warehouse_id.label("warehouse_id"),
                InventoryMovement.variant_id.label("variant_id"),
                InventoryMovement.balance_after.label("position"),
                func.row_number()
                .over(
                    partition_by=[
                        InventoryMovement.warehouse_id,
                        InventoryMovement.variant_id,
                    ],
                    order_by=[
                        InventoryMovement.created_at.desc(),
                        InventoryMovement.ledger_seq.desc(),
                    ],
                )
                .label("rn"),
            )
            .where(InventoryMovement.tenant_id == tenant_id)
            .subquery()
        )
        latest = (
            select(
                ranked.c.warehouse_id,
                ranked.c.variant_id,
                ranked.c.position,
            )
            .where(ranked.c.rn == 1)
            .subquery()
        )
        drifted = (
            await session.execute(
                select(
                    InventoryBalance.warehouse_id,
                    InventoryBalance.variant_id,
                    latest.c.position.label("expected"),
                    InventoryBalance.on_hand.label("actual"),
                ).join(
                    latest,
                    (latest.c.warehouse_id == InventoryBalance.warehouse_id)
                    & (latest.c.variant_id == InventoryBalance.variant_id),
                ).where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.on_hand != latest.c.position,
                )
            )
        ).all()
        for row in drifted:
            findings.append(
                {
                    "check": "projection",
                    "warehouse_id": row.warehouse_id,
                    "variant_id": row.variant_id,
                    "movement_id": None,
                    "expected": row.expected,
                    "actual": row.actual,
                }
            )
        # A non-zero balance with no ledger rows at all: drift by definition.
        has_ledger = (
            select(InventoryMovement.id)
            .where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.warehouse_id == InventoryBalance.warehouse_id,
                InventoryMovement.variant_id == InventoryBalance.variant_id,
            )
            .exists()
        )
        orphans = (
            await session.execute(
                select(
                    InventoryBalance.warehouse_id,
                    InventoryBalance.variant_id,
                    InventoryBalance.on_hand,
                ).where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.on_hand != 0,
                    ~has_ledger,
                )
            )
        ).all()
        for row in orphans:
            findings.append(
                {
                    "check": "projection",
                    "warehouse_id": row.warehouse_id,
                    "variant_id": row.variant_id,
                    "movement_id": None,
                    "expected": 0,
                    "actual": row.on_hand,
                }
            )

        # ---- dedupe against findings still open, then insert ---------------
        open_keys = set(
            (
                await session.execute(
                    select(
                        InventoryReconciliationFinding.check_kind,
                        InventoryReconciliationFinding.warehouse_id,
                        InventoryReconciliationFinding.variant_id,
                        InventoryReconciliationFinding.movement_id,
                    ).where(
                        InventoryReconciliationFinding.tenant_id == tenant_id,
                        InventoryReconciliationFinding.status == "OPEN",
                    )
                )
            ).all()
        )
        created = 0
        for f in findings:
            key = (f["check"], f["warehouse_id"], f["variant_id"], f["movement_id"])
            if key in open_keys:
                continue
            session.add(
                InventoryReconciliationFinding(
                    tenant_id=tenant_id,
                    warehouse_id=f["warehouse_id"],
                    variant_id=f["variant_id"],
                    check_kind=f["check"],
                    movement_id=f["movement_id"],
                    expected=f["expected"],
                    actual=f["actual"],
                )
            )
            open_keys.add(key)
            created += 1
            if created >= _RUN_BATCH_LIMIT:
                break
        await session.flush()
        return {
            "chain_mismatches": len(chain_rows),
            "projection_mismatches": len(drifted) + len(orphans),
            "findings_created": created,
        }

    @staticmethod
    async def resolve_finding(
        session: AsyncSession,
        tenant_id: UUID,
        finding_id: UUID,
        *,
        resolved_by: UUID,
        note: str | None = None,
    ) -> InventoryReconciliationFinding:
        """OPEN → RESOLVED, once. Who resolved it and why stay on the row."""
        finding = (
            await session.execute(
                select(InventoryReconciliationFinding).where(
                    InventoryReconciliationFinding.tenant_id == tenant_id,
                    InventoryReconciliationFinding.id == finding_id,
                )
            )
        ).scalar_one_or_none()
        if finding is None:
            raise NotFoundError(f"finding {finding_id} not found")
        if finding.status != "OPEN":
            raise ConflictError(
                f"finding {finding_id} is already {finding.status}"
            )
        finding.status = "RESOLVED"
        finding.resolved_at = datetime.now(UTC)
        finding.resolved_by = resolved_by
        finding.note = note
        await session.flush()
        return finding

    @staticmethod
    async def list_findings(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str = "OPEN",
        limit: int = 200,
    ) -> list[InventoryReconciliationFinding]:
        stmt = (
            select(InventoryReconciliationFinding)
            .where(InventoryReconciliationFinding.tenant_id == tenant_id)
            .order_by(
                InventoryReconciliationFinding.created_at.desc(),
                InventoryReconciliationFinding.id.desc(),
            )
            .limit(limit)
        )
        if status != "all":
            stmt = stmt.where(InventoryReconciliationFinding.status == status)
        return list((await session.execute(stmt)).scalars().all())
