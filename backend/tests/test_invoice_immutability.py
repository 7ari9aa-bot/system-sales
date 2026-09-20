"""Spec §53–54 — a closed invoice is immutable IN THE DATABASE.

`close_period` refuses to write a second snapshot for a period
(`uq_invoices_tenant_period`), but until migration `e7a8b9c0d1e2` nothing stopped
an UPDATE or a DELETE of a row that was already frozen. "Immutable" was then a
statement about the application's current code, not about the data: a psql
session, a backfill script or a reconciliation job could rewrite a closed
period's total, and the guarantee would evaporate.

These tests therefore never go through the service for the mutation under test.
They issue the UPDATE/DELETE as raw SQL — the same thing a direct client does —
so they fail if the trigger is dropped, no matter how correct the Python is. The
service's own pre-checks cannot pass this test on their own, which is the point:
it pins the DATABASE rule, not the convention.

The other half matters just as much: the rule must be NARROW.

* An ordinary invoice (no period — legacy rows, provider-created drafts) still
  moves draft -> open -> paid -> void. A blanket trigger would freeze those too
  and is the reason the guard keys on `period_start`.
* `close_period` still writes snapshots (the guard is UPDATE/DELETE only).
* Tenant teardown still works. `invoices.tenant_id` is `ON DELETE CASCADE`, so
  `DELETE FROM tenants` — which every CI teardown and the offboarding path does
  — removes the tenant's snapshots. The guard permits a referential action (the
  owner row is gone, or the statement is running inside an RI trigger) and only
  that.

A PL/pgSQL `RAISE EXCEPTION` (SQLSTATE P0001) reaches SQLAlchemy as a
driver-level `DBAPIError` — `asyncpg.exceptions.RaiseError`, which SQLAlchemy
wraps as `InternalServerError`/`DatabaseError` depending on the translation. The
assertions below catch `DBAPIError` and pin the trigger's own message, so a
different failure (a syntax error in the function, a dropped table) cannot pass
by accident. The exact subclass was not confirmed locally: no Postgres here.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.errors import ConflictError
from app.modules.billing.models import Invoice, UsageRecord
from app.modules.billing.service import BillingSnapshotService

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "e7a8b9c0d1e2_invoice_snapshot_immutability.py"
)
#: The previous head, which this migration must extend — never replace.
PREVIOUS_HEAD = "d5e6f7a8b9c0"
#: The trigger's RAISE message, used to prove WHICH failure occurred.
GUARD_MESSAGE = "frozen billing snapshot"

PERIOD_START = date(2026, 8, 1)
PERIOD_END = date(2026, 9, 1)


# ------------------------------------------------ the migration (DB-free) --


class _RecordingOp:
    """Permissive Alembic `op` stand-in: records execute(), no-ops the rest."""

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def execute(self, sql, *args, **kwargs) -> None:
        if isinstance(sql, str):
            self._captured.append(sql)

    def __getattr__(self, name: str):
        return lambda *a, **k: None


def _load_migration() -> tuple[object, list[str]]:
    captured: list[str] = []
    spec = importlib.util.spec_from_file_location(
        "invoice_immutability_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = _RecordingOp(captured)  # type: ignore[attr-defined]
    return module, captured


def test_the_migration_extends_the_existing_head() -> None:
    """A wrong `down_revision` branches the history and blocks the deploy."""
    module, _ = _load_migration()
    assert module.revision != PREVIOUS_HEAD
    assert module.down_revision == PREVIOUS_HEAD


def test_the_guard_is_a_row_trigger_on_update_and_delete() -> None:
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    sql = "\n".join(captured)

    assert "BEFORE UPDATE OR DELETE ON public.invoices" in sql
    assert "FOR EACH ROW" in sql


def test_the_guard_freezes_only_period_snapshots() -> None:
    """Pins the NARROWING, not just the existence of a trigger.

    `OLD.period_start IS NULL` is what lets an ordinary invoice keep its
    lifecycle; without it the trigger is the blanket rule that would freeze
    drafts and provider-created rows. The `tenants` probe and `pg_trigger_depth`
    are the referential-action escape, without which `DELETE FROM tenants` fails
    on every snapshot.
    """
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    sql = "\n".join(captured)

    assert "OLD.period_start IS NULL" in sql
    assert "RAISE EXCEPTION" in sql
    assert "public.tenants" in sql
    assert "pg_trigger_depth() > 1" in sql


# ------------------------------------------------------- helpers ----------


async def _closed_invoice(db: AsyncSession, tenant_id: uuid.UUID) -> Invoice:
    """Close a period through the real service — the legitimate writer."""
    db.add(
        UsageRecord(
            tenant_id=tenant_id,
            feature="messages",
            quantity=Decimal("10.00"),
            period_date=PERIOD_START,
        )
    )
    await db.flush()
    return await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )


async def _bare_tenant(db: AsyncSession) -> uuid.UUID:
    """A tenant with nothing but the columns `tenants` requires, bound for RLS.

    Mirrors the pattern the billing race test uses, so the teardown test exercises
    exactly the `DELETE FROM tenants` shape CI performs.
    """
    tenant_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tenants (id, slug, name) "
            "VALUES (:id, :slug, 'Immutable snapshot tenant')"
        ),
        {"id": tenant_id, "slug": f"inv-{tenant_id.hex[:12]}"},
    )
    await bind_tenant(db, tenant_id)
    return tenant_id


# ------------------------------------------- the database refuses edits ---


async def test_the_database_refuses_an_update_of_a_closed_invoice(
    db: AsyncSession, tenant_ctx
) -> None:
    """Raw SQL, so the refusal can only come from the database.

    A savepoint isolates the failure: the trigger aborts the statement, and
    without `begin_nested` the surrounding test transaction would be poisoned.
    """
    invoice = await _closed_invoice(db, tenant_ctx.tenant_id)

    with pytest.raises(DBAPIError) as exc:
        async with db.begin_nested():
            await db.execute(
                text(
                    "UPDATE invoices SET total = 999.99, status = 'void' WHERE id = :id"
                ),
                {"id": invoice.id},
            )

    assert GUARD_MESSAGE in str(exc.value), (
        "the UPDATE was refused by something other than the immutability trigger: "
        f"{exc.value}"
    )

    row = (
        await db.execute(
            text("SELECT total, status FROM invoices WHERE id = :id"),
            {"id": invoice.id},
        )
    ).one()
    assert row.status == "open", "the frozen snapshot's status was changed"
    assert row.total == Decimal("0.00")


async def test_the_database_refuses_a_delete_of_a_closed_invoice(
    db: AsyncSession, tenant_ctx
) -> None:
    invoice = await _closed_invoice(db, tenant_ctx.tenant_id)

    with pytest.raises(DBAPIError) as exc:
        async with db.begin_nested():
            await db.execute(
                text("DELETE FROM invoices WHERE id = :id"), {"id": invoice.id}
            )

    assert GUARD_MESSAGE in str(exc.value), (
        "the DELETE was refused by something other than the immutability trigger: "
        f"{exc.value}"
    )

    remaining = (
        await db.execute(
            text("SELECT count(*) FROM invoices WHERE id = :id"), {"id": invoice.id}
        )
    ).scalar_one()
    assert remaining == 1, "a frozen snapshot was deleted"


# ------------------------------------- and everything legitimate still works


async def test_close_period_still_writes_a_snapshot(
    db: AsyncSession, tenant_ctx
) -> None:
    """The guard is UPDATE/DELETE only — the INSERT path must be untouched."""
    invoice = await _closed_invoice(db, tenant_ctx.tenant_id)

    assert invoice.period_start == PERIOD_START
    assert invoice.period_end == PERIOD_END
    assert invoice.status == "open"

    # Read the scalars BEFORE expiring. `expire_all()` detaches every attribute,
    # and touching one afterwards in an async session raises MissingGreenlet —
    # the lazy refresh has no greenlet to run on. `tenant_ctx.tenant_id` is a
    # property over `self.tenant.id`, so it expires too. This is why the test
    # stayed red on CI for hours while SKIPPING locally (no Postgres): the DoD
    # rule "run it in both states" was unenforceable for DB-backed tests.
    invoice_id = invoice.id
    tenant_id = tenant_ctx.tenant_id

    # Re-reading proves the row is really there, not just an in-memory object.
    db.expire_all()
    reread = await BillingSnapshotService.get_snapshot(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    assert reread.id == invoice_id

    # The service's own rule is unchanged: a second close is still refused.
    with pytest.raises(ConflictError):
        await BillingSnapshotService.close_period(
            db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
        )


async def test_an_invoice_without_a_period_still_moves_through_its_lifecycle(
    db: AsyncSession, tenant_ctx
) -> None:
    """Negative control for the narrowing: a blanket trigger fails HERE.

    An ordinary invoice (no period) is not a snapshot, so `status`/`issued_at`
    must remain writable — otherwise every provider-created invoice and every
    draft-to-issued transition would be frozen by a rule about snapshots.
    """
    draft = Invoice(
        tenant_id=tenant_ctx.tenant_id,
        number=f"INV-DRAFT-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=Decimal("0.00"),
        currency="EGP",
        extra={},
    )
    db.add(draft)
    await db.flush()
    assert draft.period_start is None

    # Same trap as above: capture the id before `expire_all()` detaches it.
    draft_id = draft.id

    await db.execute(
        text("UPDATE invoices SET status = 'issued', issued_at = now() WHERE id = :id"),
        {"id": draft_id},
    )

    db.expire_all()
    reread = (
        await db.execute(select(Invoice).where(Invoice.id == draft_id))
    ).scalar_one()
    assert reread.status == "issued"
    assert reread.issued_at is not None


async def test_deleting_a_tenant_still_removes_its_frozen_snapshots(
    db: AsyncSession,
) -> None:
    """The teardown escape, pinned because CI depends on it.

    `invoices.tenant_id` is ON DELETE CASCADE, so `DELETE FROM tenants` deletes
    the tenant's snapshots. Without the escape the guard would refuse the
    cascade and break tenant offboarding — and every teardown that uses the same
    shape (`test_billing_metering`'s cleanup does).
    """
    tenant_id = await _bare_tenant(db)
    invoice = await _closed_invoice(db, tenant_id)

    await db.execute(
        text("DELETE FROM tenants WHERE id = :id"), {"id": tenant_id}
    )

    remaining = (
        await db.execute(
            text("SELECT count(*) FROM invoices WHERE id = :id"), {"id": invoice.id}
        )
    ).scalar_one()
    assert remaining == 0
