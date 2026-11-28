"""``import.run`` on a real database: batches, crash safety, idempotency, the ledger."""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.applications.apparel.modules.catalog.service import CatalogService
from app.platform.imports import apply as apply_mod
from app.platform.imports.apply import apply_batch
from app.platform.imports.fields import SHEET_PRODUCTS, SHEET_STOCK, SHEET_VARIANTS
from app.platform.imports.models import ImportRow, ImportSession
from app.platform.imports.verdicts import encode_values, values_of
from app.applications.apparel.modules.inventory.models import Warehouse
from app.platform.platform.models import Job
from app.workers import import_runner
from app.workers.import_runner import PORTS, run_batch


async def _session(db, tenant_id, status="validated") -> ImportSession:
    s = ImportSession(tenant_id=tenant_id, kind="products", file_name="f.xlsx", status=status)
    db.add(s)
    await db.flush()
    return s


def _row(s, sheet, number, action, values, status="valid") -> ImportRow:
    return ImportRow(
        tenant_id=s.tenant_id,
        session_id=s.id,
        sheet=sheet,
        row_number=number,
        raw={},
        status=status,
        parsed={"action": action, "values": encode_values(values)},
    )


async def _job(db, tenant_id, s) -> Job:
    job = Job(
        tenant_id=tenant_id,
        kind="import.run",
        status="processing",
        attempts=1,
        correlation_id=str(s.id),
    )
    db.add(job)
    await db.flush()
    return job


async def _statuses(db, s) -> dict[str, int]:
    rows = await db.execute(
        sa.text("select status, count(*) from import_rows where session_id=:i group by 1"),
        {"i": s.id},
    )
    return {k: v for k, v in rows.all()}


async def _seed_small_file(db, tenant_id):
    wh = Warehouse(tenant_id=tenant_id, name="Main", code="MAIN")
    db.add(wh)
    s = await _session(db, tenant_id)
    db.add_all(
        [
            _row(s, SHEET_PRODUCTS, 2, "create", {"product_ref": "tee", "title": "Tee"}),
            _row(
                s,
                SHEET_VARIANTS,
                2,
                "create",
                {
                    "product_ref": "tee",
                    "sku": "TEE-1",
                    "price": Decimal("99.50"),
                    "barcode": "6221",
                },
            ),
            _row(
                s,
                SHEET_STOCK,
                2,
                "create",
                {"sku": "TEE-1", "warehouse": "MAIN", "quantity": Decimal("12")},
            ),
        ]
    )
    await db.flush()
    return s


async def test_a_file_is_applied_in_order_through_the_real_services(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _seed_small_file(db, t)
    job = await _job(db, t, s)

    # The handler is one batch per run, and it works through the sheets in order. Three sheets
    # of one row each need three runs; each queues the next until nothing is left.
    results = []
    for _ in range(3):
        results.append(await run_batch(db, job))

    assert [r["applied"] for r in results] == [1, 1, 1]
    assert [r["remaining"] for r in results] == [2, 1, 0]
    assert await _statuses(db, s) == {"applied": 3}

    variant = await CatalogService.list_variants_for_products(db, t, [])  # noqa: F841
    row = (
        await db.execute(
            sa.text(
                "select v.price, v.sku, i.value, b.on_hand from product_variants v "
                "join product_identifiers i on i.variant_id=v.id "
                "join inventory_balances b on b.variant_id=v.id where v.tenant_id=:t"
            ),
            {"t": t},
        )
    ).one()
    assert (row.price, row.sku, row.value, row.on_hand) == (Decimal("99.50"), "TEE-1", "6221", 12)
    ledger = (
        await db.execute(
            sa.text("select reason, reference_type, reference_id from inventory_movements")
        )
    ).one()
    assert tuple(ledger) == ("opening_stock", "import_session", s.id)


async def test_the_session_completes_and_counts_what_happened(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _seed_small_file(db, t)
    job = await _job(db, t, s)
    for _ in range(3):
        await run_batch(db, job)

    await db.refresh(s)
    assert s.status == "completed"
    assert s.stats["applied"] == 3 and s.stats["remaining"] == 0


async def test_each_run_queues_exactly_one_follow_up_until_the_end(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _seed_small_file(db, t)
    job = await _job(db, t, s)

    await run_batch(db, job)
    queued = (
        await db.execute(
            sa.text("select count(*) from jobs where kind='import.run' and status='queued'")
        )
    ).scalar_one()
    assert queued == 1
    await run_batch(db, job)
    await run_batch(db, job)  # last batch: nothing more to queue
    queued = (
        await db.execute(
            sa.text("select count(*) from jobs where kind='import.run' and status='queued'")
        )
    ).scalar_one()
    assert queued == 2  # one per non-final batch, none for the final one


async def test_a_batch_never_exceeds_the_ceiling_even_if_asked(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _session(db, t, status="running")
    db.add_all(
        [
            _row(s, SHEET_PRODUCTS, i + 2, "create", {"product_ref": f"p{i}", "title": f"P{i}"})
            for i in range(apply_mod.BATCH_LIMIT + 25)
        ]
    )
    await db.flush()

    result = await apply_batch(
        db, t, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
    )

    assert result.taken == apply_mod.BATCH_LIMIT == 500
    assert result.remaining == 25


async def test_running_the_same_batch_twice_applies_nothing_twice(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _seed_small_file(db, t)
    job = await _job(db, t, s)
    for _ in range(3):
        await run_batch(db, job)

    again = await run_batch(db, job)  # a retried job after the work is done

    assert again.get("skipped") is True
    stock = (await db.execute(sa.text("select sum(on_hand) from inventory_balances"))).scalar_one()
    assert stock == 12
    assert (await db.execute(sa.text("select count(*) from inventory_movements"))).scalar_one() == 1


async def test_a_product_created_since_validation_is_updated_not_duplicated(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _session(db, t, status="running")
    await CatalogService.create_product(db, t, title="Taken", slug="taken")
    db.add_all(
        [
            _row(s, SHEET_PRODUCTS, 2, "create", {"product_ref": "good-a", "title": "A"}),
            # the validator saw no 'taken' product when it ran; someone created it since
            _row(s, SHEET_PRODUCTS, 3, "create", {"product_ref": "taken", "title": "Dup"}),
            _row(s, SHEET_PRODUCTS, 4, "create", {"product_ref": "good-b", "title": "B"}),
        ]
    )
    await db.flush()

    result = await apply_batch(db, t, s.id, PORTS, values_of=values_of)

    # 'taken' now exists, so the port updates it instead of failing: nothing is lost and no dup.
    assert (result.applied, result.failed) == (3, 0)
    count = (
        await db.execute(sa.text("select count(*) from products where slug in ('taken')"))
    ).scalar_one()
    assert count == 1


async def test_a_row_the_shop_refuses_is_marked_error_and_does_not_poison_the_batch(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _session(db, t, status="running")
    db.add_all(
        [
            _row(s, SHEET_PRODUCTS, 2, "create", {"product_ref": "ok", "title": "OK"}),
            # a variant for a product that does not exist: the shop refuses it at write time
            _row(
                s,
                SHEET_VARIANTS,
                2,
                "create",
                {"product_ref": "ghost", "sku": "G-1", "price": Decimal("5")},
            ),
        ]
    )
    await db.flush()

    first = await apply_batch(db, t, s.id, PORTS, values_of=values_of)
    second = await apply_batch(db, t, s.id, PORTS, values_of=values_of)

    assert (first.applied, first.failed) == (1, 0)
    assert (second.applied, second.failed) == (0, 1)
    bad = (
        await db.execute(sa.text("select errors from import_rows where status='error'"))
    ).scalar_one()
    assert bad[0]["code"] == "unknown_product"


async def test_zero_opening_stock_records_nothing_and_is_not_an_error(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    db.add(Warehouse(tenant_id=t, name="Main", code="MAIN"))
    s = await _session(db, t, status="running")
    p = await CatalogService.create_product(db, t, title="P", slug="p")
    await CatalogService.add_variant(db, t, p.id, sku="Z-1", price="1.00")
    db.add(
        _row(
            s, SHEET_STOCK, 2, "create", {"sku": "Z-1", "warehouse": "MAIN", "quantity": Decimal(0)}
        )
    )
    await db.flush()

    result = await apply_batch(db, t, s.id, PORTS, values_of=values_of)

    assert (result.applied, result.failed) == (1, 0)
    assert (await db.execute(sa.text("select count(*) from inventory_movements"))).scalar_one() == 0


async def test_a_variant_update_keeps_the_options_a_blank_cell_would_have_wiped(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    p = await CatalogService.create_product(db, t, title="P", slug="p")
    v = await CatalogService.add_variant(
        db, t, p.id, sku="S-1", option_values={"color": "Red"}, price="10.00"
    )
    s = await _session(db, t, status="running")
    db.add(
        _row(
            s,
            SHEET_VARIANTS,
            2,
            "update",
            {"product_ref": "p", "sku": "S-1", "price": Decimal("12")},
        )
    )
    await db.flush()

    await apply_batch(db, t, s.id, PORTS, values_of=values_of)

    await db.refresh(v)
    assert v.price == Decimal("12.00") and v.option_values == {"color": "Red"}


async def test_a_cancelled_session_is_left_alone(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _seed_small_file(db, t)
    s.status = "cancelled"
    job = await _job(db, t, s)
    await db.flush()

    out = await run_batch(db, job)

    assert out["skipped"] is True
    assert await _statuses(db, s) == {"valid": 3}


async def test_a_job_without_a_session_fails_loudly_so_the_runner_can_retry_or_stop(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    job = Job(
        tenant_id=t, kind="import.run", status="processing", attempts=1, correlation_id="nope"
    )
    db.add(job)
    await db.flush()
    with pytest.raises(RuntimeError, match="no session"):
        await run_batch(db, job)


def test_the_handler_is_registered_with_the_job_runner():
    from app.workers.job_runner import get_job_handler

    assert get_job_handler("import.run") is import_runner._import_run


async def test_a_database_error_on_one_row_does_not_poison_the_rest_of_the_batch(db, tenant_ctx):
    """The promise behind the per-row savepoint.

    In Postgres a failed statement aborts the whole transaction: without a savepoint around each
    row, one IntegrityError in the middle would fail every row after it with "current transaction
    is aborted", and the good rows would be lost with the bad one.
    """
    from dataclasses import replace

    t = tenant_ctx.tenant_id
    s = await _session(db, t, status="running")
    db.add_all(
        _row(s, SHEET_PRODUCTS, i + 2, "create", {"product_ref": f"p{i}", "title": f"P{i}"})
        for i in range(5)
    )
    await db.flush()

    async def flaky(session, tenant_id, ref, values, action):
        if ref == "p2":
            # a real database error, not a domain refusal: a duplicate primary key
            await session.execute(
                sa.text(
                    "insert into tenants (id, slug, name) "
                    "select id, slug, name from tenants limit 1"
                )
            )
        return await PORTS.upsert_product(session, tenant_id, ref, values, action)

    result = await apply_batch(
        db, t, s.id, replace(PORTS, upsert_product=flaky), values_of=values_of
    )

    assert (result.applied, result.failed) == (4, 1)
    assert await _statuses(db, s) == {"applied": 4, "error": 1}
    bad = (
        await db.execute(sa.text("select row_number, errors from import_rows where status='error'"))
    ).one()
    assert bad.row_number == 4 and bad.errors[0]["code"] == "database_error"
    made = (
        await db.execute(sa.text("select count(*) from products where slug like 'p_'"))
    ).scalar_one()
    assert made == 4
