"""The merchant's view of their e-receipts: what went through, what was refused, what is running
out of time. The deadline rule is the sender's own (`correction_window`), never a second copy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.core.model_registry  # noqa: F401
from app.modules.einvoice.providers.eta.sender import (
    AMENDMENT_WITH_REFERENCE,
    AMENDMENT_WITHOUT_REFERENCE,
)
from app.modules.einvoice.tracking import attention_of, summarize_documents

NOW = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)


def _doc(status="reported", hours_ago=1, document_type="simplified", errors=None, attempts=0):
    return SimpleNamespace(
        status=status,
        issued_at=NOW - timedelta(hours=hours_ago),
        document_type=document_type,
        errors=errors or [],
        delivery_attempts=attempts,
        next_attempt_at=None,
    )


# ---- one receipt -----------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["reported", "cleared", "submitted", "signed", "draft"])
def test_a_receipt_that_is_not_refused_or_failing_needs_nothing(status):
    a = attention_of(_doc(status=status), now=NOW, warn_hours=24)
    assert a.level == "ok" and a.hours_left is None


def test_a_failed_delivery_is_flagged_as_retrying_not_as_a_refusal():
    a = attention_of(_doc(status="failed", attempts=3), now=NOW, warn_hours=24)
    assert a.level == "retrying"


def test_a_refused_receipt_with_time_left_is_a_correction_due_with_the_hours_left():
    a = attention_of(_doc(status="rejected", hours_ago=10), now=NOW, warn_hours=24)
    assert a.level == "fix"
    assert a.hours_left == pytest.approx(86.0)  # 96 - 10


def test_a_refused_receipt_close_to_its_deadline_is_urgent():
    a = attention_of(_doc(status="rejected", hours_ago=80), now=NOW, warn_hours=24)
    assert a.level == "urgent" and a.hours_left == pytest.approx(16.0)


def test_a_refused_receipt_past_the_window_needs_a_late_submission_request():
    a = attention_of(_doc(status="rejected", hours_ago=100), now=NOW, warn_hours=24)
    assert a.level == "expired" and a.hours_left == 0


def test_a_return_without_a_reference_has_the_shorter_window():
    a = attention_of(
        _doc(status="rejected", hours_ago=60, document_type="return_without_reference"),
        now=NOW,
        warn_hours=24,
    )
    assert a.hours_left == pytest.approx(12.0)  # 72 - 60
    assert a.level == "urgent"


def test_the_windows_are_the_senders_own_not_a_copy():
    assert AMENDMENT_WITH_REFERENCE == timedelta(hours=96)
    assert AMENDMENT_WITHOUT_REFERENCE == timedelta(hours=72)


def test_the_warning_threshold_is_the_merchants_setting():
    doc = _doc(status="rejected", hours_ago=50)  # 46 h left
    assert attention_of(doc, now=NOW, warn_hours=24).level == "fix"
    assert attention_of(doc, now=NOW, warn_hours=48).level == "urgent"


def test_the_exact_deadline_instant_is_still_open_one_second_later_it_is_not():
    on = _doc(status="rejected", hours_ago=96)
    assert attention_of(on, now=NOW, warn_hours=24).level == "urgent"
    late = _doc(status="rejected", hours_ago=96.0003)
    assert attention_of(late, now=NOW, warn_hours=24).level == "expired"


# ---- the counters -----------------------------------------------------------------------------


def test_the_summary_counts_every_kind_and_the_ones_that_need_the_merchant():
    docs = [
        _doc("reported"),
        _doc("reported"),
        _doc("cleared"),
        _doc("submitted"),
        _doc("signed"),
        _doc("failed"),
        _doc("rejected", hours_ago=10),
        _doc("rejected", hours_ago=90),
        _doc("rejected", hours_ago=200),
        _doc("cancelled"),
    ]
    s = summarize_documents(docs, now=NOW, warn_hours=24)
    assert s["total"] == 10
    assert s["accepted"] == 3  # reported + cleared
    assert s["waiting"] == 2  # submitted + signed
    assert s["retrying"] == 1
    assert s["rejected"] == 3
    assert s["fix_now"] == 2  # still correctable
    assert s["urgent"] == 1
    assert s["expired"] == 1
    assert s["needs_attention"] == 3  # the three refused; the retrying one fixes itself


def test_an_empty_shop_has_all_zeros_not_missing_keys():
    s = summarize_documents([], now=NOW, warn_hours=24)
    assert s["total"] == 0 and s["needs_attention"] == 0 and s["expired"] == 0


# ---- through the real app, on a real database -------------------------------------------------
# The merchant's two endpoints: the right shop's receipts only, behind the right permission, the
# refused ones nearest their deadline first, and the counters agreeing with the list.

import uuid  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.db import bind_tenant  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.einvoice.service import EInvoiceService  # noqa: E402
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx  # noqa: E402
from tests.test_eta_db_layer import _ctx, _device, _other_tenant  # noqa: E402

LIST = "/api/v1/einvoice/receipts"
SUMMARY = "/api/v1/einvoice/receipts/summary"


def _app(db, tenant_id, perms=("orders:read",)) -> FastAPI:
    app = create_app()

    async def _as_shop() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes=set(perms),
        )

    app.dependency_overrides[get_tenant_ctx] = _as_shop
    return app


def _http(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _issue(db, tid, dev, number, status, *, hours_ago=1.0, errors=None):
    doc = await EInvoiceService.issue_einvoice(db, tid, _ctx(tid, number), device_id=dev.id)
    doc.status = status
    doc.errors = errors or []
    doc.issued_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    await db.flush()
    return doc


async def test_the_list_shows_only_this_shops_receipts(db, tenant_ctx):
    # Two layers keep shops apart: the query's own tenant filter and the database's row-level
    # security (these tests run as the app role, which RLS binds). Removing ONE of them leaves this
    # passing, on purpose: the guarantee is that a shop never sees another's receipts.
    t = tenant_ctx.tenant_id
    other = await _other_tenant(db)
    await bind_tenant(db, other)  # RLS: another shop's rows can only be written as that shop
    theirs = await _device(db, other, serial="THEIRS-1")
    await _issue(db, other, theirs, "R-THEIRS", "reported")
    await bind_tenant(db, t)
    mine = await _device(db, t, serial="MINE-1")
    await _issue(db, t, mine, "R-MINE", "reported")

    async with _http(_app(db, t)) as c:
        body = (await c.get(LIST)).json()
        counters = (await c.get(SUMMARY)).json()

    assert [r["invoice_number"] for r in body["items"]] == ["R-MINE"]
    assert body["total"] == 1 and counters["total"] == 1


async def test_a_user_without_the_read_permission_is_refused(db, tenant_ctx):
    async with _http(_app(db, tenant_ctx.tenant_id, perms=())) as c:
        assert (await c.get(LIST)).status_code == 403
        assert (await c.get(SUMMARY)).status_code == 403


async def test_refused_receipts_come_first_closest_deadline_at_the_top(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    dev = await _device(db, t, serial="ORD-1")
    await _issue(db, t, dev, "OK-1", "reported", hours_ago=0.5)
    await _issue(db, t, dev, "FIX-1", "rejected", hours_ago=10, errors=["bad item code"])
    await _issue(db, t, dev, "URGENT-1", "rejected", hours_ago=90)
    await _issue(db, t, dev, "GONE-1", "rejected", hours_ago=200)
    await _issue(db, t, dev, "RETRY-1", "failed", hours_ago=2)

    async with _http(_app(db, t)) as c:
        items = (await c.get(LIST)).json()["items"]

    assert [r["invoice_number"] for r in items] == [
        "GONE-1",
        "URGENT-1",
        "FIX-1",
        "RETRY-1",
        "OK-1",
    ]
    assert [r["attention"] for r in items] == ["expired", "urgent", "fix", "retrying", "ok"]
    fix = next(r for r in items if r["invoice_number"] == "FIX-1")
    assert fix["errors"] == ["bad item code"] and 85 < fix["hours_left"] < 87


async def test_the_counters_agree_with_the_list(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    dev = await _device(db, t, serial="CNT-1")
    for i, (st, h) in enumerate(
        [("reported", 1), ("cleared", 1), ("submitted", 1), ("failed", 1)]
        + [("rejected", 10), ("rejected", 90), ("rejected", 200)]
    ):
        await _issue(db, t, dev, f"C-{i}", st, hours_ago=h)

    async with _http(_app(db, t)) as c:
        s = (await c.get(SUMMARY)).json()
        listed = (await c.get(LIST, params={"limit": 200})).json()["items"]

    assert s["total"] == len(listed) == 7
    assert (s["accepted"], s["waiting"], s["retrying"], s["rejected"]) == (2, 1, 1, 3)
    assert (s["fix_now"], s["urgent"], s["expired"], s["needs_attention"]) == (2, 1, 1, 3)
    assert s["warn_hours"] == 24  # the merchant's setting, at its default


async def test_a_group_filter_and_paging(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    dev = await _device(db, t, serial="PG-1")
    for i in range(5):
        await _issue(db, t, dev, f"P-{i}", "reported", hours_ago=i + 1)
    await _issue(db, t, dev, "P-REJ", "rejected", hours_ago=5)

    async with _http(_app(db, t)) as c:
        rej = (await c.get(LIST, params={"group": "rejected"})).json()
        page = (await c.get(LIST, params={"group": "accepted", "limit": 2, "offset": 2})).json()
        bad = await c.get(LIST, params={"group": "nonsense"})

    assert [r["invoice_number"] for r in rej["items"]] == ["P-REJ"]
    assert page["total"] == 5 and len(page["items"]) == 2
    assert bad.status_code == 422


async def test_the_warning_threshold_is_the_shops_setting(db, tenant_ctx):
    from app.modules.settings.service import SettingsService

    t = tenant_ctx.tenant_id
    dev = await _device(db, t, serial="WRN-1")
    await _issue(db, t, dev, "W-1", "rejected", hours_ago=50)  # 46 h left

    async with _http(_app(db, t)) as c:
        before = (await c.get(SUMMARY)).json()
        await SettingsService(db, t).set("einvoice.warn_hours_before_deadline", 48)
        after = (await c.get(SUMMARY)).json()

    assert (before["urgent"], before["warn_hours"]) == (0, 24)
    assert (after["urgent"], after["warn_hours"]) == (1, 48)


async def test_a_day_filter_includes_the_whole_last_day(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    dev = await _device(db, t, serial="DAY-1")
    doc = await _issue(db, t, dev, "D-1", "reported")
    doc.issued_at = datetime(2026, 11, 20, 23, 30, tzinfo=UTC)
    await db.flush()

    async with _http(_app(db, t)) as c:
        inside = (
            await c.get(LIST, params={"date_from": "2026-11-20", "date_to": "2026-11-20"})
        ).json()
        outside = (await c.get(LIST, params={"date_from": "2026-11-21"})).json()

    assert inside["total"] == 1 and outside["total"] == 0


def test_no_route_here_can_change_a_receipt():
    methods = {
        m
        for r in create_app().openapi()["paths"].items()
        if r[0].startswith("/api/v1/einvoice/receipts")
        for m in r[1]
    }
    assert methods == {"get"}
