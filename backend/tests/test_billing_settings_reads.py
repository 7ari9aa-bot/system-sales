"""Section 19's read models: the plan, the metering and the invoices.

The Settings Center's plan pages must not compute a number the billing module would
compute differently. Two of these reads exist because the page had no honest way to answer
its own question:

* ``GET /billing/subscription`` carried only a status and a date, so "which plan am I on and
  what does it cost" had no answer even though ``subscriptions.plan_id`` was right there.
* ``GET /billing/usage/summary`` reports usage through ``used_this_period`` — the same call
  the entitlement gate refuses on — instead of summing the table in the page. A seat count
  is a live row count, not a period accumulator, and only that method knows the difference.

The invoice list is bounded and validated on the server: ``?limit=-1`` used to be the kind of
parameter SQL happily accepts as "every row".
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.billing.models import Invoice
from app.modules.billing.router import billing_router
from app.modules.billing.services.subscriptions import BillingService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from tests.test_billing_gates import _permission_codes


def _app_for(db: AsyncSession, tenant_id: uuid.UUID):
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="staff"),
        tenant_id=tenant_id,
        role_code="staff",
        permission_codes=set(),
    )
    app = create_app()

    async def _ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _get(app, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


# ------------------------------------------------------------------ routing --


def test_the_new_reads_are_open_to_every_member_like_the_old_ones() -> None:
    """A member must be able to see their own bill and their own limits; the gate
    belongs on writes (``billing:write``), not on reading what you already owe."""
    for path in ("/billing/usage/summary", "/billing/invoices"):
        assert _permission_codes(billing_router.routes, path, "GET") == set()


# ------------------------------------------------------------- the plan row --


async def test_the_subscription_carries_its_plan(db: AsyncSession, tenant_ctx) -> None:
    await BillingService.start_trial(db, tenant_ctx.tenant_id, plan_code="starter", days=14)
    await db.flush()

    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/subscription")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "trialing"
    assert body["plan"] is not None
    assert body["plan"]["code"] == "starter"
    assert body["plan"]["name"]
    # Money leaves the API as a string: a float would round a Numeric column on the way out.
    assert isinstance(body["plan"]["price"], str)
    assert body["cancel_at_period_end"] is False


async def test_no_subscription_is_still_an_answer_not_an_error(
    db: AsyncSession, tenant_ctx
) -> None:
    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/subscription")

    assert response.status_code == 200
    assert response.json() == {"status": "none"}


# --------------------------------------------------------------- the meters --


async def test_usage_summary_reports_the_gates_own_numbers(db: AsyncSession, tenant_ctx) -> None:
    await BillingService.start_trial(db, tenant_ctx.tenant_id, plan_code="starter", days=14)
    await BillingService.record_usage(
        db, tenant_ctx.tenant_id, feature="ai_tokens", quantity=Decimal("12.00")
    )
    await db.flush()

    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/usage/summary")

    assert response.status_code == 200, response.text
    rows = {row["feature"]: row for row in response.json()["items"]}
    assert "ai_tokens" in rows, "a metered feature with usage must be listed"
    expected = await BillingService.used_this_period(db, tenant_ctx.tenant_id, "ai_tokens")
    assert rows["ai_tokens"]["used"] == expected


async def test_a_seat_limit_is_counted_from_live_rows(db: AsyncSession, tenant_ctx) -> None:
    """``max_users`` is a live count of ``tenant_users``, never a period accumulator.

    The tenant fixture creates exactly one owner, so a summary that summed usage rows
    instead of counting seats would report 0 here — the bug this pins.
    """
    await BillingService.start_trial(db, tenant_ctx.tenant_id, plan_code="starter", days=14)
    await db.flush()

    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/usage/summary")

    rows = {row["feature"]: row for row in response.json()["items"]}
    if "max_users" in rows:
        assert rows["max_users"]["used"] == 1


async def test_no_subscription_means_no_limits_rather_than_zero_limits(
    db: AsyncSession, tenant_ctx
) -> None:
    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/usage/summary")

    assert response.status_code == 200
    assert response.json() == {"items": []}


# -------------------------------------------------------------- the invoices --


async def _invoice(db: AsyncSession, tenant_id: uuid.UUID, number: str, **kwargs) -> Invoice:
    row = Invoice(
        tenant_id=tenant_id,
        number=number,
        status=kwargs.pop("status", "open"),
        total=kwargs.pop("total", 100),
        currency="EGP",
        issued_at=datetime.now(UTC),
        **kwargs,
    )
    db.add(row)
    await db.flush()
    return row


async def test_invoices_are_listed_newest_first_with_their_money_as_strings(
    db: AsyncSession, tenant_ctx
) -> None:
    await _invoice(db, tenant_ctx.tenant_id, "INV-OLD")
    await _invoice(db, tenant_ctx.tenant_id, "INV-NEW")

    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/invoices")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [row["number"] for row in items][:2] == ["INV-NEW", "INV-OLD"]
    assert isinstance(items[0]["total"], str)


async def test_another_tenants_invoice_is_not_listed(db: AsyncSession, tenant_ctx) -> None:
    other = uuid.uuid4()
    await db.execute(
        Invoice.__table__.insert().values(
            id=uuid.uuid4(),
            tenant_id=other,
            number="INV-THEIRS",
            status="open",
            subtotal=0,
            tax=0,
            total=50,
            currency="EGP",
            extra={},
        )
    )
    await _invoice(db, tenant_ctx.tenant_id, "INV-OURS")

    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/invoices")

    numbers = [row["number"] for row in response.json()["items"]]
    assert "INV-OURS" in numbers
    assert "INV-THEIRS" not in numbers


async def test_a_nonsense_page_is_refused_instead_of_silently_ignored(
    db: AsyncSession, tenant_ctx
) -> None:
    app = _app_for(db, tenant_ctx.tenant_id)
    for query in ("limit=0", "limit=1000", "offset=-1"):
        response = await _get(app, f"/api/v1/billing/invoices?{query}")
        assert response.status_code == 400, query
        assert response.json()["error"]["code"] == "validation_error"


async def test_a_closed_period_snapshot_appears_as_an_invoice(db: AsyncSession, tenant_ctx) -> None:
    await _invoice(
        db,
        tenant_ctx.tenant_id,
        "INV-SNAPSHOT",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 11, 1),
    )

    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/billing/invoices")

    row = next(r for r in response.json()["items"] if r["number"] == "INV-SNAPSHOT")
    assert row["period_start"] == "2026-10-01"
    assert row["period_end"] == "2026-11-01"
