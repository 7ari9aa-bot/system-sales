"""Shared dependencies, routers, and helpers for marketing routers."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from app.core.pagination import decode_cursor, encode_cursor, page_slice, paginate
from app.modules.billing.service import EntitlementService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.marketing import analytics

router = APIRouter(tags=["marketing"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("marketing:write"))]

MAX_WINDOW_DAYS = 365
MAX_PAGE_SIZE = 200

_wire_money = analytics.wire_money


def _missing_query_params(*names: str) -> NoReturn:
    """Answer 422 in the shape the framework uses for a bad query parameter."""
    raise HTTPException(
        status_code=422,
        detail=[
            {
                "type": "missing",
                "loc": ["query", name],
                "msg": f"provide {' or '.join(names)}",
                "input": None,
            }
            for name in names
        ],
    )


__all__ = [
    "EntitlementService",
    "MAX_PAGE_SIZE",
    "MAX_WINDOW_DAYS",
    "TenantContext",
    "TenantCtxDep",
    "WriteCtx",
    "_missing_query_params",
    "_wire_money",
    "analytics_router",
    "decode_cursor",
    "encode_cursor",
    "page_slice",
    "paginate",
    "require_permission",
    "router",
]
