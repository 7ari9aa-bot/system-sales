"""GAP M12, data half — the backfill over rows the old normalizer wrote.

``app/core/contact_norm`` fixed the WRITES. Rows written before it are still
wrong in the database, in two different ways that must not be treated the same:

* a legal-but-local spelling (``01001234567``, ``+20 100 123 4567``, mixed-case
  email) is REVERSIBLE: the same digits are still in the column, so a rewrite to
  E.164 loses nothing.
* the deleted ``normalize_phone_e164`` defaulted to Iraq (+964), so ``0020…``
  became ``+9640201…``. That string is a legal E.164 shape and could also be a
  genuine Iraqi number — the fabrication is IRREVERSIBLE. It is marked for a
  human, never rewritten.

Rewriting two rows onto one canonical value would break
``uq_customers_tenant_phone``, so the migration detects that clash first and
reports it instead of merging: an automated data migration has no business
picking which customer's order history survives.

Pure cases (the classifier, the collision detector, route order) run locally.
The migration's effect on real rows is DB-backed: skipped locally without
``DATABASE_URL_APP_ADMIN``, proven in CI.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contact_norm import (
    STATE_BLANK,
    STATE_CANONICAL,
    STATE_CORRUPTED,
    STATE_REVERSIBLE,
    STATE_UNPARSEABLE,
    classify_stored_email,
    classify_stored_phone,
    find_canonical_collisions,
    legacy_fabrication,
)
from app.modules.customers.models import Customer
from app.modules.customers.router import router
from app.modules.customers.service import CustomerService

EGYPT = "+201001234567"
IRAQI_MOBILE = "+9647701234567"
FABRICATED = "+9640201001234567"

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "d5a1c7e94b02_m12_contact_backfill.py"
)
FLAG_PATH = ("data_quality", "m12_contact_backfill")


# ---------------------------------------------------------------------------
# A — classification of a STORED value. Pure, so it runs here.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    ["01001234567", "+20 100 123 4567", "00201001234567", "201001234567", "(0100) 123 4567"],
)
def test_a_legal_local_spelling_of_a_stored_phone_is_reversible(spelling: str) -> None:
    assert classify_stored_phone(spelling) == STATE_REVERSIBLE


def test_an_already_canonical_stored_phone_is_left_alone() -> None:
    assert classify_stored_phone(EGYPT) == STATE_CANONICAL
    assert classify_stored_phone(IRAQI_MOBILE) == STATE_CANONICAL


def test_a_number_that_can_never_be_canonicalized_is_unparseable() -> None:
    for garbage in ("call me maybe", "0100123", "00012345678", "+2010a3f9b2c1"):
        assert classify_stored_phone(garbage) == STATE_UNPARSEABLE
    assert classify_stored_phone(None) == STATE_BLANK
    assert classify_stored_phone("   ") == STATE_BLANK


def test_the_iraq_default_fabrication_is_corrupted_not_reversible() -> None:
    """``+9640201001234567`` is a LEGAL E.164 shape — so the corruption check
    must run before "is it already canonical?", or it reads back as fine."""
    assert classify_stored_phone(FABRICATED) == STATE_CORRUPTED
    assert classify_stored_phone("+96401001234567") == STATE_CORRUPTED


def test_a_genuine_iraq_number_is_never_flagged_as_fabricated() -> None:
    """The tell is the surviving Egyptian trunk 0 after +964; a real Iraqi
    subscriber number has no leading zero in E.164 form."""
    for real in (IRAQI_MOBILE, "+964112345678", "+964512345678"):
        assert classify_stored_phone(real) != STATE_CORRUPTED


def test_the_fabrication_note_recovers_the_pre_corruption_string() -> None:
    """The digits the old default WRAPPED are a fact, not a guess — that is
    what a human needs in order to resolve the row."""
    detail = legacy_fabrication(FABRICATED)
    assert detail is not None
    assert detail.legacy_raw == "0201001234567"
    assert detail.suspected_phone == EGYPT
    assert legacy_fabrication(IRAQI_MOBILE) is None
    assert legacy_fabrication(EGYPT) is None


def test_a_stored_email_is_classified_by_case_and_padding_only() -> None:
    assert classify_stored_email("  Ali.Hassan@EXAMPLE.com ") == STATE_REVERSIBLE
    assert classify_stored_email("ali.hassan@example.com") == STATE_CANONICAL
    assert classify_stored_email("no-at-sign") == STATE_UNPARSEABLE
    assert classify_stored_email(None) == STATE_BLANK


# ---------------------------------------------------------------------------
# B — the collision detector. Pure: it is a grouping over rows, not a query.
# ---------------------------------------------------------------------------


def test_two_rows_that_land_on_one_canonical_phone_are_a_collision() -> None:
    tenant = uuid.uuid4()
    groups = find_canonical_collisions(
        [
            (tenant, uuid.uuid4(), "01001234567"),
            (tenant, uuid.uuid4(), "+20 100 123 4567"),
        ]
    )
    assert len(groups) == 1
    assert groups[0]["canonical"] == EGYPT
    assert len(groups[0]["row_ids"]) == 2


def test_a_rewrite_that_would_step_on_an_existing_canonical_row_is_a_collision() -> None:
    """The clash is with the value the DATABASE already holds, not only between
    two legacy spellings — rewriting the local one is what raises 23505."""
    tenant = uuid.uuid4()
    holder, mover = uuid.uuid4(), uuid.uuid4()
    groups = find_canonical_collisions([(tenant, holder, EGYPT), (tenant, mover, "00201001234567")])
    assert [str(i) for i in groups[0]["row_ids"]] == sorted([str(holder), str(mover)])


def test_collisions_are_per_tenant_and_ordered_deterministically() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    rows = [
        (a, uuid.uuid4(), "01001234567"),
        (a, uuid.uuid4(), "201001234567"),
        (b, uuid.uuid4(), "01001234567"),
        (b, uuid.uuid4(), "0100-123-4567"),
    ]
    groups = find_canonical_collisions(rows)
    assert [str(g["tenant_id"]) for g in groups] == sorted([str(a), str(b)]), (
        "groups must come back in a stable order or the migration is not deterministic"
    )
    assert all(g["canonical"] == EGYPT for g in groups)


def test_unfixable_values_never_join_a_collision_group() -> None:
    """A corrupted or unparseable phone is not being rewritten, so it cannot
    clash with anything — including another copy of itself."""
    tenant = uuid.uuid4()
    groups = find_canonical_collisions(
        [
            (tenant, uuid.uuid4(), FABRICATED),
            (tenant, uuid.uuid4(), FABRICATED),
            (tenant, uuid.uuid4(), "call me maybe"),
            (tenant, uuid.uuid4(), None),
        ]
    )
    assert groups == []


# ---------------------------------------------------------------------------
# C — the staff read surface must be reachable (route order, no DB).
# ---------------------------------------------------------------------------


def test_the_data_quality_route_shadows_no_customer_id_route() -> None:
    """``/customers/{customer_id}`` matches any string, and a non-UUID one fails
    validation there instead of falling through — so the literal path has to be
    registered FIRST."""
    paths = [r.path for r in router.routes]
    assert "/customers/contact-data-issues" in paths
    assert paths.index("/customers/contact-data-issues") < paths.index("/customers/{customer_id}")


# ---------------------------------------------------------------------------
# D — the migration over real rows (CI; skipped without a database)
# ---------------------------------------------------------------------------


class _BindOp:
    """Stand-in for alembic's ``op`` bound to the test's own transaction."""

    def __init__(self, bind: Any) -> None:
        self._bind = bind

    def get_bind(self) -> Any:
        return self._bind


async def _drive(db: AsyncSession, direction: str) -> None:
    module = _load_migration()
    conn = await db.connection()

    def _run(sync_conn: Any) -> None:
        module.op = _BindOp(sync_conn)  # type: ignore[attr-defined]
        getattr(module, direction)()

    await conn.run_sync(_run)
    db.expire_all()


def _load_migration():
    assert MIGRATION_PATH.exists(), f"backfill migration missing: {MIGRATION_PATH}"
    spec = importlib.util.spec_from_file_location("m12_backfill_under_test", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_backfill_revision_sits_on_the_current_head() -> None:
    """Pinned statically: a second head silently splits the migration graph."""
    module = _load_migration()
    assert module.down_revision == "c4f7a9b1d3e5"
    assert module.revision == "d5a1c7e94b02"


async def _legacy(
    db: AsyncSession, tenant_id: uuid.UUID, *, phone: str | None, email: str | None = None
) -> uuid.UUID:
    """Insert a row the way the OLD code did — raw, never through the service.

    The id comes back rather than the instance: every migration drive expires
    the identity map so a later SELECT sees its raw UPDATE, and reading an
    attribute off an expired instance lazy-loads — which has no greenlet
    outside the async driver.
    """
    customer = Customer(
        id=uuid.uuid4(), tenant_id=tenant_id, name="Legacy", phone=phone, email=email
    )
    db.add(customer)
    await db.flush()
    return customer.id


async def _stored(db: AsyncSession, customer_id: uuid.UUID) -> tuple[str | None, dict]:
    row = (
        await db.execute(select(Customer.phone, Customer.extra).where(Customer.id == customer_id))
    ).one()
    return row[0], row[1] or {}


async def test_upgrade_rewrites_reversible_values_in_place(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    phone_id = await _legacy(db, tenant_id, phone="01001234567", email="  Ali.Hassan@EXAMPLE.com ")
    spaced_id = await _legacy(db, tenant_id, phone="+20 999 888 7766")

    await _drive(db, "upgrade")

    assert await _stored(db, phone_id) == (
        EGYPT,
        {
            "data_quality": {
                "m12_contact_backfill": {
                    "phone_from": "01001234567",
                    "email_from": "  Ali.Hassan@EXAMPLE.com ",
                    "revision": "d5a1c7e94b02",
                }
            }
        },
    )
    stored_spaced, _ = await _stored(db, spaced_id)
    assert stored_spaced == "+209998887766"


async def test_upgrade_leaves_canonical_and_unparseable_values_untouched(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    canonical_id = await _legacy(db, tenant_id, phone=IRAQI_MOBILE)
    garbage_id = await _legacy(db, tenant_id, phone="call me maybe")
    empty_id = await _legacy(db, tenant_id, phone=None)

    await _drive(db, "upgrade")

    for row_id, expected in (
        (canonical_id, IRAQI_MOBILE),
        (garbage_id, "call me maybe"),
        (empty_id, None),
    ):
        stored, extra = await _stored(db, row_id)
        assert stored == expected
        assert FLAG_PATH[1] not in (extra.get("data_quality") or {}), (
            "nothing was fixed, so nothing may be marked"
        )


async def test_upgrade_marks_a_fabricated_phone_for_review_without_rewriting_it(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    row_id = await _legacy(db, tenant_id, phone=FABRICATED)

    await _drive(db, "upgrade")

    stored, extra = await _stored(db, row_id)
    assert stored == FABRICATED, "an irreversible corruption must never be guessed at"
    assert extra["data_quality"]["m12_contact_backfill"] == {
        "phone_status": "needs_review",
        "legacy_raw": "0201001234567",
        "suspected_phone": EGYPT,
        "revision": "d5a1c7e94b02",
    }


async def test_a_marked_row_is_queryable_by_its_mark(db: AsyncSession, tenant_ctx):
    """The whole point of the mark is that a human can FIND the queue."""
    from sqlalchemy import func

    tenant_id = tenant_ctx.tenant_id
    row_id = await _legacy(db, tenant_id, phone=FABRICATED)
    await _legacy(db, tenant_id, phone=IRAQI_MOBILE)
    await _drive(db, "upgrade")

    marked = (
        (
            await db.execute(
                select(Customer.id).where(
                    Customer.tenant_id == tenant_id,
                    func.jsonb_extract_path(Customer.extra, *FLAG_PATH).isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert marked == [row_id], "only the row the migration marked comes back"


async def test_upgrade_skips_and_reports_a_collision_instead_of_writing_it(
    db: AsyncSession, tenant_ctx
):
    """Both spellings canonicalize to one value: rewriting the second would
    violate uq_customers_tenant_phone, so neither moves and both are marked."""
    tenant_id = tenant_ctx.tenant_id
    holder_id = await _legacy(db, tenant_id, phone=EGYPT)
    mover_id = await _legacy(db, tenant_id, phone="00201001234567")

    await _drive(db, "upgrade")

    assert (await _stored(db, holder_id))[0] == EGYPT
    assert (await _stored(db, mover_id))[0] == "00201001234567"
    flag = (await _stored(db, mover_id))[1]["data_quality"]["m12_contact_backfill"]
    assert flag["phone_collision"]["canonical"] == EGYPT
    assert flag["phone_collision"]["peer_customer_ids"] == [str(holder_id)]


async def test_upgrade_is_idempotent(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    await _legacy(db, tenant_id, phone="01001234567")
    await _legacy(db, tenant_id, phone=FABRICATED)
    await _legacy(db, tenant_id, phone="00201001234567")
    await _legacy(db, tenant_id, phone="0100-999-8877")
    await _drive(db, "upgrade")

    before = (
        await db.execute(select(Customer.id, Customer.phone, Customer.extra).order_by(Customer.id))
    ).all()
    await _drive(db, "upgrade")
    after = (
        await db.execute(select(Customer.id, Customer.phone, Customer.extra).order_by(Customer.id))
    ).all()

    assert [(r[0], r[1], r[2]) for r in before] == [(r[0], r[1], r[2]) for r in after]


async def test_downgrade_restores_every_value_it_changed(db: AsyncSession, tenant_ctx):
    """A data rewrite that cannot be undone is not a data migration."""
    tenant_id = tenant_ctx.tenant_id
    fixed_id = await _legacy(db, tenant_id, phone="0100-555-7788", email="A@Example.com")
    flagged_id = await _legacy(db, tenant_id, phone=FABRICATED)
    mover_id = await _legacy(db, tenant_id, phone="01001234567")
    holder_id = await _legacy(db, tenant_id, phone=EGYPT)  # the clash partner of `mover`

    await _drive(db, "upgrade")
    assert (await _stored(db, fixed_id))[0] == "+201005557788"

    await _drive(db, "downgrade")

    for row_id, previous in (
        (fixed_id, "0100-555-7788"),
        (flagged_id, FABRICATED),
        (mover_id, "01001234567"),
        (holder_id, EGYPT),
    ):
        stored, stored_extra = await _stored(db, row_id)
        assert stored == previous
        # Downgrade removes the marks too — including the ones recording work it
        # deliberately did not do, which upgrade will put back.
        assert stored_extra == {}, f"residue left on {row_id}"
    assert await db.scalar(select(Customer.email).where(Customer.id == fixed_id)) == (
        "A@Example.com"
    )


async def test_the_report_lists_every_marked_row_for_the_tenant(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    corrupted_id = await _legacy(db, tenant_id, phone=FABRICATED)
    clash_a_id = await _legacy(db, tenant_id, phone=EGYPT)
    clash_b_id = await _legacy(db, tenant_id, phone="201001234567")
    clean_id = await _legacy(db, tenant_id, phone=IRAQI_MOBILE)
    await _drive(db, "upgrade")

    items = await CustomerService.contact_data_quality_report(db, tenant_id)

    assert {i["customer_id"] for i in items} == {
        str(corrupted_id),
        str(clash_a_id),
        str(clash_b_id),
    }
    by_id = {i["customer_id"]: i for i in items}
    assert by_id[str(corrupted_id)]["issues"] == ["phone_legacy_default_country"]
    assert by_id[str(corrupted_id)]["suspected_phone"] == EGYPT
    assert by_id[str(clash_b_id)]["issues"] == ["phone_canonical_collision"]
    assert by_id[str(clash_b_id)]["canonical_phone"] == EGYPT
    assert by_id[str(clash_b_id)]["peer_customer_ids"] == [str(clash_a_id)]
    assert by_id[str(clash_a_id)]["phone_state"] == STATE_CANONICAL
    assert str(clean_id) not in by_id


async def test_the_report_is_scoped_to_the_caller_tenant(db: AsyncSession, tenant_ctx):
    other = uuid.uuid4()
    await _legacy(db, tenant_ctx.tenant_id, phone=FABRICATED)
    # A foreign tenant's queue is not this tenant's, marked or not.
    assert await CustomerService.contact_data_quality_report(db, other) == []


async def test_the_endpoint_redacts_every_phone_column_it_returns(db: AsyncSession, tenant_ctx):
    """§146 redacts by field NAME, and the report renames phones — so the
    renamed keys have to be on the redaction list too."""
    from types import SimpleNamespace

    from app.modules.customers.router import list_contact_data_issues

    tenant_id = tenant_ctx.tenant_id
    await _legacy(db, tenant_id, phone=FABRICATED)
    await _drive(db, "upgrade")
    ctx = SimpleNamespace(
        session=db,
        tenant_id=tenant_id,
        user=tenant_ctx.user,
        permission_codes={"customers:write"},
    )

    body = await list_contact_data_issues(ctx, limit=50)  # type: ignore[arg-type]

    assert body["count"] == 1
    item = body["items"][0]
    assert item["phone"] is None
    assert item["legacy_raw"] is None
    assert item["suspected_phone"] is None
    assert item["issues"] == ["phone_legacy_default_country"]


# ---------------------------------------------------------------------------
# E — the PATCH branch that writes columns directly still has to normalize.
# ---------------------------------------------------------------------------


async def test_the_if_match_patch_branch_stores_a_canonical_phone(db: AsyncSession, tenant_ctx):
    """``apply_versioned_update`` takes plain column values into one UPDATE, so
    it never passed through the service's normalization: a drawer PATCHing with
    an ETag wrote the raw spelling straight into the uniqueness key."""
    from types import SimpleNamespace

    from fastapi import Response

    from app.modules.customers.router import CustomerUpdate, update_customer

    tenant_id = tenant_ctx.tenant_id
    # A legacy row: stored raw, because the old code stored whatever was typed.
    row_id = await _legacy(db, tenant_id, phone="0100-123-4567")
    # Read the token as a column: touching row.version after a flush would
    # lazy-load, and there is no greenlet here to do it in.
    version = await db.scalar(select(Customer.version).where(Customer.id == row_id))
    ctx = SimpleNamespace(
        session=db,
        tenant_id=tenant_id,
        user=tenant_ctx.user,
        permission_codes={"customers:write", "pii:read"},
    )

    await update_customer(
        row_id,
        CustomerUpdate(phone="00201001234567", email=" SAMEH@Example.COM "),
        ctx,  # type: ignore[arg-type]
        Response(),
        f'"{version}"',
    )

    assert await db.scalar(select(Customer.phone).where(Customer.id == row_id)) == EGYPT
    assert await db.scalar(select(Customer.email).where(Customer.id == row_id)) == (
        "sameh@example.com"
    )
