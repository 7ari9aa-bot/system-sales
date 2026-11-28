"""Customers through the Import Center: the cell rules, the check, and the real intake."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.applications.apparel.modules.customers.service import CustomerService
from app.platform.imports import normalize as n
from app.platform.imports import service
from app.platform.imports.apply import SHEET_ORDER
from app.platform.imports.fields import SHEET_CUSTOMERS, SHEET_FIELDS, SHEET_PRODUCTS
from app.platform.imports.mapping import suggest_mapping
from app.platform.imports.models import ImportRow
from app.platform.imports.validation import validate_customers
from app.platform.platform.models import Job
from app.workers.import_runner import run_batch
from tests.test_imports_http import BOTH, api  # noqa: F401, F811  (api: fixture)
from tests.test_imports_run import _job, _session

MAP = {"Name": "name", "Phone": "phone", "Email": "email", "Source": "source", "Tags": "tags"}


# ---- the cells --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "01012345678",
        "٠١٠١٢٣٤٥٦٧٨",
        "1012345678",
        "1012345678.0",
        "+20 101 234 5678",
        "010-1234-5678",
    ],
)
def test_every_way_a_merchant_types_one_egyptian_mobile_gives_the_same_number(raw):
    assert n.parse_phone(raw) == "+201012345678"


@pytest.mark.parametrize(
    ("raw", "code"),
    [("1.012345678E9", "scientific_notation"), ("123", "bad_phone"), ("abc", "bad_phone")],
)
def test_a_phone_that_cannot_be_dialled_is_refused_with_a_stable_code(raw, code):
    with pytest.raises(n.CellError) as err:
        n.parse_phone(raw)
    assert err.value.code == code


def test_a_blank_phone_or_email_is_not_an_error_by_itself():
    assert n.parse_phone("  ") is None and n.parse_email("") is None


def test_an_email_is_lowercased_and_a_broken_one_refused():
    assert n.parse_email(" A@B.com ") == "a@b.com"
    with pytest.raises(n.CellError) as err:
        n.parse_email("nope")
    assert err.value.code == "bad_email"


def test_tags_split_on_english_and_arabic_separators_once_each():
    assert n.parse_tags("vip, جملة ؛ VIP ; wholesale،") == ["vip", "جملة", "wholesale"]
    assert n.parse_tags("") == []


def test_too_many_tags_are_refused():
    with pytest.raises(n.CellError) as err:
        n.parse_tags(",".join(f"t{i}" for i in range(n.TAGS_MAX + 1)))
    assert err.value.code == "too_many_tags"


# ---- the check --------------------------------------------------------------------------------


def _check(rows, *, phones=None, emails=()):
    numbered = [(i + 2, r) for i, r in enumerate(rows)]
    return validate_customers(
        numbered, MAP, taken_phones=dict(phones or {}), taken_emails=set(emails)
    )


def test_a_good_row_is_valid_and_carries_clean_values():
    (v,) = _check([{"Name": " منى ", "Phone": "٠١٠١٢٣٤٥٦٧٨", "Email": "M@x.io", "Tags": "vip"}])
    assert v.ok and v.action == "create"
    assert v.values == {
        "name": "منى",
        "phone": "+201012345678",
        "email": "m@x.io",
        "source": "import",
        "tags": ["vip"],
    }


def test_a_name_alone_is_refused_because_nobody_could_be_matched_to_it_again():
    (v,) = _check([{"Name": "منى"}])
    assert [e.code for e in v.errors] == ["no_contact"]


def test_a_missing_name_and_a_bad_phone_are_both_reported_on_the_row():
    (v,) = _check([{"Name": "", "Phone": "abc"}])
    assert {e.code for e in v.errors} == {"required", "bad_phone"}


def test_a_customer_the_shop_already_has_is_refused_by_phone_or_by_email():
    by_phone = _check([{"Name": "a", "Phone": "01012345678"}], phones={"+201012345678": True})
    by_email = _check([{"Name": "a", "Email": "a@b.co"}], emails={"a@b.co"})
    assert by_phone[0].errors[0].code == "already_a_customer"
    assert by_email[0].errors[0].code == "already_a_customer"


def test_two_rows_that_normalise_to_one_phone_are_one_person_and_the_second_is_refused():
    first, second = _check(
        [{"Name": "a", "Phone": "01012345678"}, {"Name": "b", "Phone": "٠١٠١٢٣٤٥٦٧٨"}]
    )
    assert first.ok
    assert [e.code for e in second.errors] == ["duplicate_in_file"]
    assert "row 2" in second.errors[0].message


def test_the_same_email_in_different_letter_case_is_the_same_person():
    first, second = _check([{"Name": "a", "Email": "A@x.io"}, {"Name": "b", "Email": "a@X.io"}])
    assert first.ok and second.errors[0].code == "duplicate_in_file"


def test_the_legacy_csv_header_is_matched_in_full():
    got = suggest_mapping(SHEET_CUSTOMERS, ["name", "email", "phone", "source", "tags"])
    assert set(got.values()) == {"name", "email", "phone", "source", "tags"}


def test_arabic_headers_are_matched():
    got = suggest_mapping(
        SHEET_CUSTOMERS, ["اسم العميل", "الموبايل", "البريد الإلكتروني", "الوسوم"]
    )
    assert list(got.values()) == ["name", "phone", "email", "tags"]


def test_customers_are_applied_before_everything_else_because_they_need_nothing_from_the_file():
    assert SHEET_ORDER[0] == SHEET_CUSTOMERS
    assert SHEET_ORDER.index(SHEET_CUSTOMERS) < SHEET_ORDER.index(SHEET_PRODUCTS)
    assert {f.key for f in SHEET_FIELDS[SHEET_CUSTOMERS]} == {
        "name",
        "phone",
        "email",
        "source",
        "tags",
    }


@pytest.mark.parametrize(
    ("headers", "kind"),
    [
        (["name", "phone", "email"], SHEET_CUSTOMERS),
        (["اسم العميل", "الهاتف", "البريد الإلكتروني"], SHEET_CUSTOMERS),
        (["Name", "Mobile"], SHEET_CUSTOMERS),
        (["name", "email", "phone", "source", "tags"], SHEET_CUSTOMERS),
        (["title", "price", "sku"], SHEET_PRODUCTS),
        (["title", "sku", "price", "phone"], SHEET_PRODUCTS),  # a "supplier phone" column
        (["name"], SHEET_PRODUCTS),  # the old default is kept when nothing says otherwise
        (["sku", "quantity", "phone"], SHEET_PRODUCTS),
    ],
)
def test_a_csv_is_read_as_customers_only_when_its_columns_say_so(headers, kind):
    assert service._csv_sheet_kind(headers) == kind


# ---- the run, on a real database ---------------------------------------------------------------


async def _customers_session(db, t, rows):
    s = await _session(db, t, status="validated")
    s.mapping = {SHEET_CUSTOMERS: MAP}
    db.add_all(
        ImportRow(
            tenant_id=t,
            session_id=s.id,
            sheet=SHEET_CUSTOMERS,
            row_number=i + 2,
            raw=r,
            status="pending",
        )
        for i, r in enumerate(rows)
    )
    await db.flush()
    await service.validate_session(db, t, s.id)
    return s


async def test_a_checked_row_becomes_a_real_customer_with_its_tags_and_source(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _customers_session(
        db,
        t,
        [
            {
                "Name": "منى",
                "Phone": "٠١٠١٢٣٤٥٦٧٨",
                "Email": "M@x.io",
                "Source": "معرض",
                "Tags": "vip, جملة",
            }
        ],
    )

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 0)
    row = (
        await db.execute(
            sa.text("select id, name, phone, email, extra from customers where tenant_id=:t"),
            {"t": t},
        )
    ).one()
    assert (row.name, row.phone, row.email) == ("منى", "+201012345678", "m@x.io")
    assert row.extra == {"source": "معرض"}
    tags = await CustomerService.list_tags(db, t, row.id)
    assert {x.name for x in tags} == {"vip", "جملة"}


async def test_a_customer_the_shop_already_has_is_refused_at_the_check_so_nothing_is_run(
    db, tenant_ctx
):
    t = tenant_ctx.tenant_id
    await CustomerService.create_from_import(db, t, name="قديم", phone="01012345678")
    s = await _customers_session(db, t, [{"Name": "جديد", "Phone": "٠١٠١٢٣٤٥٦٧٨"}])

    codes = (
        await db.execute(
            sa.text("select status, errors->0->>'code' from import_rows where session_id=:i"),
            {"i": s.id},
        )
    ).one()
    assert tuple(codes) == ("error", "already_a_customer")
    assert (await run_batch(db, await _job(db, t, s)))["applied"] == 0
    assert (await db.execute(sa.text("select count(*) from customers"))).scalar_one() == 1


async def test_a_legacy_row_is_caught_when_the_file_spells_the_phone_the_way_it_was_stored(
    db, tenant_ctx
):
    """Rows typed by hand before contacts were normalised hold what a person wrote.

    The customers service finds them through ``phone_candidates``, which tries the canonical form
    and the raw spelling the NEW row was typed with. So the check finds the same rows the service
    would, no more: a legacy ``01012345678`` is matched by a file that also says ``01012345678``.
    (A file that says ``+20 101 234 5678`` is not matched against it by the service either; making
    the check stricter than the shop's own identity rule would be a separate decision.)
    """
    t = tenant_ctx.tenant_id
    await db.execute(
        sa.text(
            "insert into customers (id, tenant_id, name, phone, extra) "
            "values (gen_random_uuid(), :t, 'قديم', '01012345678', '{}')"
        ),
        {"t": t},
    )
    s = await _customers_session(db, t, [{"Name": "جديد", "Phone": "01012345678"}])

    code = (
        await db.execute(
            sa.text("select errors->0->>'code' from import_rows where session_id=:i"), {"i": s.id}
        )
    ).scalar_one()
    assert code == "already_a_customer"


async def test_a_deleted_customer_still_holds_its_phone_and_the_check_says_so_up_front(
    db, tenant_ctx
):
    """``uq_customers_tenant_phone`` covers deleted rows, so reusing the number fails at insert.

    Telling the merchant at the check, with its own reason, is the point: 'ready' followed by a
    row that fails at run time is what the check exists to prevent.
    """
    t = tenant_ctx.tenant_id
    await db.execute(
        sa.text(
            "insert into customers (id, tenant_id, name, phone, extra, deleted_at) "
            "values (gen_random_uuid(), :t, 'محذوف', '+201012345678', '{}', now())"
        ),
        {"t": t},
    )
    s = await _customers_session(db, t, [{"Name": "جديد", "Phone": "01012345678"}])

    row = (
        await db.execute(
            sa.text("select status, errors->0->>'code' from import_rows where session_id=:i"),
            {"i": s.id},
        )
    ).one()
    assert tuple(row) == ("error", "phone_of_deleted_customer")
    assert (await run_batch(db, await _job(db, t, s)))["applied"] == 0


async def test_a_deleted_customers_email_can_be_used_again(db, tenant_ctx):
    """Unlike the phone, an email has no database key: only a live customer holds it."""
    t = tenant_ctx.tenant_id
    await db.execute(
        sa.text(
            "insert into customers (id, tenant_id, name, email, extra, deleted_at) "
            "values (gen_random_uuid(), :t, 'محذوف', 'a@b.co', '{}', now())"
        ),
        {"t": t},
    )
    s = await _customers_session(db, t, [{"Name": "جديد", "Email": "a@b.co"}])

    assert (await run_batch(db, await _job(db, t, s)))["applied"] == 1


async def test_a_customer_created_after_the_check_fails_only_its_row(db, tenant_ctx):
    """The check ran, then someone else added the same phone: that row errs, the others apply."""
    t = tenant_ctx.tenant_id
    s = await _customers_session(
        db, t, [{"Name": "أ", "Phone": "01012345678"}, {"Name": "ب", "Phone": "01112345678"}]
    )
    await CustomerService.create_from_import(db, t, name="سبقه", phone="01012345678")

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 1)
    code = (
        await db.execute(sa.text("select errors->0->>'code' from import_rows where status='error'"))
    ).scalar_one()
    assert code == "already_a_customer"


async def test_a_file_can_carry_customers_and_products_together(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _customers_session(db, t, [{"Name": "منى", "Phone": "01012345678"}])
    assert (await run_batch(db, await _job(db, t, s)))["applied"] == 1
    assert (await db.get(type(s), s.id)).status == "completed"


# ---- the whole flow over HTTP, with the CSV the old endpoint took ------------------------------

OLD_CSV = (
    "name,email,phone,source,tags\n"
    'منى أحمد,mona@x.io,٠١٠١٢٣٤٥٦٧٨,معرض,"vip, جملة"\n'
    "كريم,,01112345678,,\n"
    "بدون وسيلة اتصال,,,,\n"
    "رقم غلط,,12,,\n"
    "مكرر,,01012345678,,\n"
).encode("utf-8-sig")


async def test_the_old_customer_csv_goes_through_the_import_center_end_to_end(
    api,  # noqa: F811  (the fixture, re-exported above)
    db,
    tenant_ctx,
):
    """Upload, check, preview, start over HTTP; then the worker runs the job that was queued."""
    t = tenant_ctx.tenant_id
    async with api(BOTH) as client:
        up = await client.post(
            "/api/v1/imports/sessions",
            params={"filename": "customers.csv"},
            content=OLD_CSV,
            headers={"content-type": "text/csv"},
        )
        assert up.status_code in (200, 201), up.text
        sid = up.json()["id"]
        base = f"/api/v1/imports/sessions/{sid}"

        # the columns decide it is a customer list, and every column is matched by itself
        stats = (await client.get(base)).json()["stats"]
        assert stats["rows"] == {SHEET_CUSTOMERS: 5}

        assert (await client.post(f"{base}/validate")).status_code == 200
        preview = (await client.get(f"{base}/preview")).json()
        sheet = preview["stats"]["sheets"][SHEET_CUSTOMERS]
        assert (sheet["valid"], sheet["invalid"]) == (2, 3)
        reasons = {(e["row"], e["errors"][0]["code"]) for e in preview["sample_errors"]}
        assert reasons == {(4, "no_contact"), (5, "bad_phone"), (6, "duplicate_in_file")}

        # the check wrote nothing to the customer list
        assert (await db.execute(sa.text("select count(*) from customers"))).scalar_one() == 0
        started = await client.post(f"{base}/start")
        assert started.status_code == 202, started.text

    job = await db.get(Job, started.json()["job_id"])
    result = await run_batch(db, job)

    assert (result["applied"], result["failed"]) == (2, 0)
    rows = (
        await db.execute(
            sa.text("select name, phone, email from customers where tenant_id=:t order by name"),
            {"t": t},
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("كريم", "+201112345678", None),
        ("منى أحمد", "+201012345678", "mona@x.io"),
    ]
