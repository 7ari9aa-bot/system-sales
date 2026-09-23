"""B — the billing capability gates, and the one write that had no gate at all.

What already exists (so this is NOT re-invented here): plans carry features in
`plans.features` JSONB, `BillingService.start_trial` copies the numeric ones into
`entitlements` rows (`billing/service.py:100-114`), and
`EntitlementService.can/ensure` (`billing/service.py:265-333`) answer a
capability by mapping it through `_CAPABILITY_FEATURE`
(`billing/service.py:45`) onto that row, with `_DERIVED_USAGE`
(`billing/service.py:65`) counting live seats instead of a per-period
accumulator. Those are consulted on the live write paths
(`identity/router.py:291` seats, `ai/hooks.py:72` AI auto-reply,
`customers/router.py:441` channel allowlist), and `tests/test_entitlements.py`
already pins the seat and channel refusals.

What was missing is on the ROUTE side, and it is inside this module:
`POST /billing/usage` — the write that appends to the very table the tenant's
invoice is metered from — accepted any authenticated member of the tenant
(`TenantCtxDep` alone). A `staff` account, which the seeded role matrix gives no
`billing:*` code at all, could mint usage rows: shrink their own measured spend
or inflate it. It now carries the same `billing:write` gate its neighbours
`/billing/start-trial` and `/billing/periods/close` already used.

The first cases are DB-free and assert the ROUTE declares the gate (a check
moved into an endpoint body can be bypassed by a later refactor); the rest drive
the real ASGI app and assert the status code and the error code, both ways.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.billing.models import UsageRecord
from app.modules.billing.router import billing_router, webhooks_router
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx


def _permission_codes(routes, path: str, method: str) -> set[str]:
    """RBAC codes a route declares, found by walking its dependency tree."""
    for route in routes:
        if route.path == path and method in route.methods:
            codes: set[str] = set()
            stack = list(route.dependant.dependencies)
            while stack:
                dependant = stack.pop()
                code = getattr(dependant.call, "code", None)
                if code:
                    codes.add(code)
                stack.extend(dependant.dependencies)
            return codes
    raise AssertionError(f"{method} {path} is not routed")


def _app_for(db: AsyncSession, tenant_id: uuid.UUID, *, permissions: set[str]):
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="staff"),
        tenant_id=tenant_id,
        role_code="staff",
        permission_codes=permissions,
    )

    app = create_app()

    async def _ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _usage_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(UsageRecord)
            .where(UsageRecord.tenant_id == tenant_id)
        )
    ).scalar_one()


async def _post(app, path: str, payload: dict):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=payload)


# --------------------------------------------------- the gates on the routes --


def test_recording_usage_is_a_billing_write() -> None:
    assert _permission_codes(billing_router.routes, "/billing/usage", "POST") == {
        "billing:write"
    }


def test_the_writes_that_were_already_gated_stay_gated() -> None:
    """Pinned so a refactor cannot quietly drop them while 'simplifying'."""
    assert _permission_codes(
        billing_router.routes, "/billing/start-trial", "POST"
    ) == {"billing:write"}
    assert _permission_codes(
        billing_router.routes, "/billing/periods/close", "POST"
    ) == {"billing:write"}
    assert _permission_codes(
        webhooks_router.routes, "/webhook-endpoints", "POST"
    ) == {"settings:write"}


def test_the_billing_reads_stay_open_to_every_member() -> None:
    """A tenant under §48 recovery must still see its own subscription; the gate
    belongs on writes, not on reading one's own bill."""
    assert _permission_codes(billing_router.routes, "/billing/subscription", "GET") == set()
    assert _permission_codes(
        billing_router.routes, "/billing/periods/snapshot", "GET"
    ) == set()


# --------------------------------------------------------- refusal, for real --


async def test_usage_post_refuses_a_member_without_billing_write(
    db: AsyncSession, tenant_ctx
) -> None:
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"inventory:read"})

    response = await _post(
        app, "/api/v1/billing/usage", {"feature": "messages", "quantity": "5.00"}
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "permission_denied"
    assert "billing:write" in body["error"]["message"]
    assert await _usage_count(db, tenant_ctx.tenant_id) == 0


async def test_usage_post_records_for_a_member_who_has_it(
    db: AsyncSession, tenant_ctx
) -> None:
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"billing:write"})

    response = await _post(
        app, "/api/v1/billing/usage", {"feature": "messages", "quantity": "5.00"}
    )

    assert response.status_code == 201, response.text
    assert response.json()["used_this_period"] == 5
    assert await _usage_count(db, tenant_ctx.tenant_id) == 1


async def test_a_negative_usage_row_is_still_rejected(
    db: AsyncSession, tenant_ctx
) -> None:
    """The gate must not become the only defence: `quantity > 0` was already the
    model's rule, and a caller with billing:write must not erase a period."""
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"billing:write"})

    response = await _post(
        app, "/api/v1/billing/usage", {"feature": "messages", "quantity": "-5.00"}
    )

    assert response.status_code == 422
    assert await _usage_count(db, tenant_ctx.tenant_id) == 0


_PERIOD = {
    "period_start": date(2026, 1, 1).isoformat(),
    "period_end": date(2026, 1, 31).isoformat(),
}


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/billing/periods/close", _PERIOD),
        ("/api/v1/billing/start-trial", {}),
    ],
)
async def test_the_other_billing_writes_refuse_the_same_caller(
    db: AsyncSession, tenant_ctx, path: str, payload: dict
) -> None:
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"orders:write"})

    response = await _post(app, path, payload)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
