"""The reservation expiry sweep is WIRED, and proven through the scheduler.

The recurring defect in this repo is code that nothing calls. `expire_stale()`
is implemented and the scheduler registers an `expire_reservations` handler, but
a handler only runs if a `ScheduledJob` row exists for it and the poller claims
it. The unit test in `test_inventory_reservation_ledger.py` calls
`expire_stale()` directly — which proves the sweep works but is blind to whether
*anything ever runs it*.

This file closes that gap on two levels:

1. Static / AST pins (run everywhere, skip locally is impossible for them):
   a producer exists that inserts a periodic `expire_reservations` row, the
   handler wired to that job type is the one that calls `expire_stale`, and the
   producer is invoked from `SchedulerWorker.run` — so the call path is live from
   boot, not dead code. `run()` never seeds `ensure_recurring_jobs` = the exact
   invisible dead path these pins are built to catch.

2. A DB-backed end-to-end chain test (CI-only, skips without
   DATABASE_URL_APP_ADMIN): given a DUE `expire_reservations` job, driving the
   scheduler's claim/execute loop flips stale ACTIVE reservations to EXPIRED and
   writes their `release` movement rows — going THROUGH the handler, never by
   calling `expire_stale()` directly. The invariant the sweep must keep — a
   release records only what it actually freed and touches no physical stock —
   is asserted on the ledger.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    Warehouse,
)
from app.modules.inventory.service import InventoryService
from app.modules.orders.service import OrderService
from app.modules.platform.models import ScheduledJob
from app.workers import scheduler_worker as sw

# ------------------------------------------------------------------ sources --

_WORKER_SRC = pathlib.Path(sw.__file__).read_text(encoding="utf-8")
_WORKER_TREE = ast.parse(_WORKER_SRC)


def _func(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    return None


def _class(tree: ast.AST, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _called_names(scope: ast.AST) -> set[str]:
    """Bare names invoked as functions inside `scope` (ast.Call func=Name)."""
    return {
        node.func.id
        for node in ast.walk(scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _method_names(attr_calls: ast.AST) -> set[str]:
    """`.method(...)` names invoked inside `scope`."""
    return {
        node.func.attr
        for node in ast.walk(attr_calls)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _value_keywords(scope: ast.AST) -> set[str]:
    """Keyword names passed to any `.values(...)` call inside `scope`."""
    found: set[str] = set()
    for node in ast.walk(scope):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "values"
        ):
            found.update(kw.arg for kw in node.keywords if kw.arg)
    return found


# ------------------------------------------------ static pins (always run) ---


def test_expire_reservations_is_a_recurring_job_with_a_handler() -> None:
    """The job type must be BOTH in the recurring registry (so a row is seeded)
    AND have a registered handler (so the claimed row does something)."""
    assert "expire_reservations" in sw.RECURRING_JOBS
    assert "expire_reservations" in sw._HANDLERS, (
        "expire_reservations is recurring but no handler is registered — the "
        "row would be claimed and failed as 'no handler'"
    )


def test_the_registered_handler_calls_expire_stale() -> None:
    """The handler wired to `expire_reservations` must actually run the sweep,
    not an empty stub."""
    fn = _func(_WORKER_TREE, "_handle_expire_reservations")
    assert fn is not None, "_handle_expire_reservations was renamed or deleted"
    attrs = _method_names(fn)
    assert "expire_stale" in attrs, (
        "the expire_reservations handler no longer calls expire_stale()"
    )


def test_a_producer_inserts_the_recurring_row_idempotently() -> None:
    """`ensure_recurring_jobs` must build a ScheduledJob row over the recurring
    registry, keyed by an idempotency_key with ON CONFLICT DO NOTHING — this is
    the insert-if-absent that makes exactly-once hold across boots/replicas."""
    fn = _func(_WORKER_TREE, "ensure_recurring_jobs")
    assert fn is not None, "the producer ensure_recurring_jobs disappeared"
    # It inserts ScheduledJob rows and iterates the recurring registry.
    assert "pg_insert" in _called_names(fn), "producer no longer builds an INSERT"
    referenced = {node.id for node in ast.walk(fn) if isinstance(node, ast.Name)}
    assert "ScheduledJob" in referenced
    assert "RECURRING_JOBS" in referenced, (
        "producer no longer loops RECURRING_JOBS — a new sweep would never seed"
    )
    # ...and does it idempotently on the unique key.
    assert _value_keywords(fn) >= {"job_type", "idempotency_key"}, (
        "producer's insert lost job_type/idempotency_key columns"
    )
    assert "on_conflict_do_nothing" in _method_names(fn), (
        "producer lost ON CONFLICT DO NOTHING — a restart would multiply the row"
    )


def test_the_producer_is_invoked_at_worker_start() -> None:
    """The whole point: a producer nobody calls is dead code. `SchedulerWorker`
    must call `ensure_recurring_jobs` from its lifecycle (`run`/bootstrap), so a
    boot actually seeds the sweep instead of polling an empty table forever."""
    cls = _class(_WORKER_TREE, "SchedulerWorker")
    assert cls is not None
    run_fn = None
    for node in cls.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            run_fn = node
    assert run_fn is not None, "SchedulerWorker.run is gone"
    assert "ensure_recurring_jobs" in _called_names(run_fn), (
        "SchedulerWorker.run no longer seeds recurring jobs — expire_reservations "
        "would be produced by nobody, the exact dead-path this repo keeps hitting"
    )


def test_the_scheduler_is_a_started_pool() -> None:
    """`run()` only executes if the worker is in the pool registry the entrypoint
    starts."""
    from app.workers.run import POOLS

    assert POOLS.get("scheduler") is sw.SchedulerWorker


# -------------------------------------------------- the live chain (CI-only) --


async def _seed_stale_hold(
    db: AsyncSession, tenant_id: uuid.UUID
) -> tuple[InventoryReservation, Warehouse, object]:
    """A real checkout, then force its reservation past TTL.

    Uses the production write path (OrderService.create_order -> reserve) so the
    hold row and the durable reservation exist exactly as they do for an abandoned
    cart; only the expiry timestamp is pushed into the past.
    """
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Expiry Buyer"
    )
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Expiry WH",
        code=f"EW-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()

    product = await CatalogService.create_product(
        db, tenant_id, title="Expiry Product", slug=f"e-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="10.00")
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 3}],
        warehouse_id=warehouse.id,
    )
    reservation = (
        await db.execute(
            select(InventoryReservation).where(
                InventoryReservation.order_id == order.id
            )
        )
    ).scalar_one()
    assert reservation.status == "ACTIVE"
    reservation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.flush()
    return reservation, warehouse, variant


async def _due_expire_job(db: AsyncSession, tenant_id: uuid.UUID) -> ScheduledJob:
    job = ScheduledJob(
        tenant_id=tenant_id,
        job_type="expire_reservations",
        status="queued",
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        payload={},
        attempts=0,
        max_attempts=5,
        idempotency_key=f"recurring:expire_reservations:{tenant_id}",
    )
    db.add(job)
    await db.flush()
    return job


class _NoBus:
    async def ack(self, *a, **k):  # pragma: no cover - never consumed
        return None


async def test_a_due_expire_job_runs_the_sweep_end_to_end(
    db: AsyncSession, tenant_ctx
) -> None:
    """THE chain: driving the scheduler's claim loop on a due `expire_reservations`
    row must flip the stale reservation and write its release row — never by
    calling expire_stale() directly (it isn't imported/called in this test)."""
    tenant_id = tenant_ctx.tenant_id
    reservation, warehouse, variant = await _seed_stale_hold(db, tenant_id)
    await _due_expire_job(db, tenant_id)

    worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]
    processed = await worker._drain_tenant(db, tenant_id)

    assert processed == 1, "the due expire_reservations job was not claimed/run"

    refreshed = (
        await db.execute(
            select(InventoryReservation)
            .where(InventoryReservation.id == reservation.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.status == "EXPIRED", (
        "the scheduler ran but the stale hold did not expire"
    )

    # The release row is the ledger fact that the sweep freed availability, and
    # it names the reservation it released.
    releases = list(
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.tenant_id == tenant_id,
                    InventoryMovement.reason == "reservation_release",
                    InventoryMovement.reference_id == reservation.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(m.direction, m.quantity) for m in releases] == [("release", 3)], (
        "the sweep did not record exactly what it freed (3 units)"
    )

    balance = await InventoryService.get_balance(db, tenant_id, variant.id, warehouse.id)
    assert balance.reserved == 0, "the hold was not given back to availability"

    # Invariant: the sweep touches ONLY availability — no physical row appeared,
    # so on_hand still equals the sum of physical movements.
    physical = (
        await db.execute(
            select(
                func.sum(
                    case(
                        (InventoryMovement.direction == "in", InventoryMovement.quantity),
                        (InventoryMovement.direction == "out", -InventoryMovement.quantity),
                        else_=0,
                    )
                )
            ).where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.variant_id == variant.id,
                InventoryMovement.warehouse_id == warehouse.id,
                InventoryMovement.direction.in_(("in", "out")),
            )
        )
    ).scalar_one()
    assert int(physical or 0) == balance.on_hand == 10
    sales = (
        await db.execute(
            select(func.count())
            .select_from(InventoryMovement)
            .where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.reason == "sale",
            )
        )
    ).scalar_one()
    assert sales == 0, "the expiry sweep sold stock — it may only release holds"

    # A recurring sweep re-arms its own row rather than completing it, so the
    # next run is produced by the same machinery (exactly-once row survives).
    job = (
        await db.execute(
            select(ScheduledJob).where(
                ScheduledJob.idempotency_key
                == f"recurring:expire_reservations:{tenant_id}"
            )
        )
    ).scalar_one()
    assert job.status == "queued"
    assert job.run_at > datetime.now(UTC) - timedelta(seconds=5)
    assert job.result == {"count": 1}
