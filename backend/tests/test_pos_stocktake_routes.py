"""The stocktake routes: who may call what, what a bad body does, and the whole flow end to end.

The permission gate sits in `Depends(...)`, so calling the route function skips it. These tests
read the gate off the LIVE route (so deleting a Depends fails here) and also run it explicitly
against real staff / manager contexts.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as BodyError

from app.core.errors import PermissionDeniedError
from app.modules.errors import ConflictError
from app.modules.identity.deps import require_permission
from app.modules.pos.router import (
    OpenStocktakeRequest,
    StocktakeCountsRequest,
    approve_stocktake,
    cancel_stocktake,
    get_stocktake,
    list_stocktakes,
    open_stocktake,
    save_stocktake_counts,
)
from tests.test_inventory_stock_view import _ctx, _gate_codes, _variant

pytestmark = pytest.mark.asyncio

_WRITE = {"inventory:write"}
_ROUTES = [
    ("/pos/stocktakes", "GET", _WRITE),
    ("/pos/stocktakes", "POST", _WRITE),
    ("/pos/stocktakes/{stocktake_id}", "GET", _WRITE),
    ("/pos/stocktakes/{stocktake_id}/counts", "PUT", _WRITE),
    ("/pos/stocktakes/{stocktake_id}/cancel", "POST", _WRITE),
    # approving is what changes the balances: a manager's act, not any stock clerk's
    ("/pos/stocktakes/{stocktake_id}/approve", "POST", {"pos:override"}),
]


@pytest.mark.parametrize(("path", "method", "expected"), _ROUTES)
async def test_every_route_is_wired_to_its_permission_on_the_live_router(path, method, expected):
    assert _gate_codes(path, method) == expected


async def test_staff_can_neither_open_count_nor_approve(db, tenant_ctx):
    staff = await _ctx(db, tenant_ctx, "staff")
    for code in ("inventory:write", "pos:override"):
        with pytest.raises(PermissionDeniedError):
            await require_permission(code)(staff)


async def test_a_manager_holds_both_permissions(db, tenant_ctx):
    manager = await _ctx(db, tenant_ctx, "manager")
    for code in ("inventory:write", "pos:override"):
        assert await require_permission(code)(manager) is manager


@pytest.mark.parametrize("bad", [-1, 1_000_001, 2.5, "3", True])
async def test_a_bad_count_in_the_body_is_rejected_before_it_reaches_the_service(bad):
    with pytest.raises(BodyError):
        StocktakeCountsRequest(
            counts=[{"variant_id": "00000000-0000-0000-0000-000000000001", "counted_qty": bad}]
        )


async def test_the_body_rejects_an_empty_sheet_a_bad_id_and_an_oversized_note():
    with pytest.raises(BodyError):
        StocktakeCountsRequest(counts=[])
    with pytest.raises(BodyError):
        StocktakeCountsRequest(counts=[{"variant_id": "not-a-uuid", "counted_qty": 1}])
    with pytest.raises(BodyError):
        OpenStocktakeRequest(note="x" * 256)


async def test_null_is_accepted_as_not_counted():
    body = StocktakeCountsRequest(
        counts=[{"variant_id": "00000000-0000-0000-0000-000000000001", "counted_qty": None}]
    )
    assert body.counts[0].counted_qty is None


async def test_the_whole_flow_through_the_routes(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=10)
    manager = await _ctx(db, tenant_ctx, "manager")

    sheet = await open_stocktake(OpenStocktakeRequest(note="جرد نهاية الشهر"), manager)
    assert sheet["status"] == "OPEN" and sheet["note"] == "جرد نهاية الشهر"
    line = next(r for r in sheet["lines"] if r["variant_id"] == str(variant.id))
    assert (line["expected_qty"], line["counted_qty"]) == (10, None)

    with pytest.raises(ConflictError):  # a second open count on the same shop
        await open_stocktake(OpenStocktakeRequest(), manager)

    body = StocktakeCountsRequest(counts=[{"variant_id": str(variant.id), "counted_qty": 7}])
    assert await save_stocktake_counts(__import__("uuid").UUID(sheet["id"]), body, manager) == {
        "saved": 1
    }

    listed = await list_stocktakes(manager)
    mine = next(r for r in listed if r["id"] == sheet["id"])
    assert mine["status"] == "OPEN" and mine["counted"] == 1 and mine["lines"] >= 1

    # a saved count moves nothing yet
    again = await get_stocktake(__import__("uuid").UUID(sheet["id"]), manager)
    assert (
        next(r for r in again["lines"] if r["variant_id"] == str(variant.id))["current_qty"] == 10
    )

    result = await approve_stocktake(__import__("uuid").UUID(sheet["id"]), manager)
    assert result["adjusted"] == 1 and result["counted"] == 1

    done = await get_stocktake(__import__("uuid").UUID(sheet["id"]), manager)
    row = next(r for r in done["lines"] if r["variant_id"] == str(variant.id))
    assert done["status"] == "APPROVED" and row["current_qty"] == 7 and row["applied_delta"] == -3

    with pytest.raises(ConflictError):
        await approve_stocktake(__import__("uuid").UUID(sheet["id"]), manager)


async def test_cancel_through_the_route_leaves_stock_alone(db, tenant_ctx):
    import uuid

    _p, variant, _w = await _variant(db, tenant_ctx, stock=5)
    manager = await _ctx(db, tenant_ctx, "manager")
    sheet = await open_stocktake(OpenStocktakeRequest(), manager)
    body = StocktakeCountsRequest(counts=[{"variant_id": str(variant.id), "counted_qty": 0}])
    await save_stocktake_counts(uuid.UUID(sheet["id"]), body, manager)
    assert await cancel_stocktake(uuid.UUID(sheet["id"]), manager) == {"status": "CANCELLED"}
    after = await get_stocktake(uuid.UUID(sheet["id"]), manager)
    assert after["status"] == "CANCELLED"
    assert next(r for r in after["lines"] if r["variant_id"] == str(variant.id))["current_qty"] == 5
