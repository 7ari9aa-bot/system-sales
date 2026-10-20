"""POST /warehouses/ensure-default: the first-use gap.

A brand-new shop has no warehouse and no API creates one, yet a POS profile, a register
and every stock movement need a warehouse_id. This endpoint makes the cashier setup
reachable: manager-only, and repeat-safe (the second call returns the same row).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.errors import PermissionDeniedError
from app.main import create_app
from app.modules.catalog.routers import taxonomy
from app.modules.identity.deps import require_permission
from app.modules.inventory.models import Warehouse
from tests.conftest import TenantCtx


def test_route_is_post_only_on_its_own_path_and_requires_settings_write() -> None:
    spec = create_app().openapi()["paths"]
    assert "post" in spec["/api/v1/warehouses/ensure-default"]
    # the read-only list stays the only thing on /warehouses itself
    assert sorted(spec["/api/v1/warehouses"]) == ["get"]
    route = next(
        r for r in taxonomy.router.routes if getattr(r, "path", "") == "/warehouses/ensure-default"
    )
    gates = [d.call for d in route.dependant.dependencies if isinstance(d.call, require_permission)]
    assert [g.code for g in gates] == ["settings:write"]


@pytest.mark.asyncio
async def test_a_cashier_without_settings_write_is_refused() -> None:
    class _Cashier:
        permission_codes = frozenset({"orders:write"})  # can sell, cannot configure

    with pytest.raises(PermissionDeniedError):
        await require_permission("settings:write")(_Cashier())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_first_call_creates_main_and_second_call_returns_the_same_row(
    tenant_ctx: TenantCtx,
) -> None:
    ctx = tenant_ctx
    a = await taxonomy.ensure_default_warehouse(ctx)  # type: ignore[arg-type]
    b = await taxonomy.ensure_default_warehouse(ctx)  # type: ignore[arg-type]
    assert a["id"] == b["id"]
    assert a["is_active"] is True
    n = (
        await ctx.session.execute(
            select(func.count()).select_from(Warehouse).where(Warehouse.tenant_id == ctx.tenant_id)
        )
    ).scalar_one()
    assert n == 1, "repeat-safe: a second click must not create a second warehouse"
