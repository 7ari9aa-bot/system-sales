"""Orders placed on a Fihrist Sites storefront (website-platform integration, phase 3).

Fihrist is the source of truth: the storefront sends WHAT was bought, never what it costs.
Prices come from this tenant's own catalog and price ladder, stock is reserved here, and the
order lands in the same pipeline as every other order (outbox event, status history). A cart
that cannot be filled in full is refused whole: no partial order, no stock held.

Authentication is the same per-tenant key the catalog bridge uses (``X-WP-Key``), resolved by
that module so there is one place that decides which key maps to which tenant. It lives in the
orders module, not in the catalog bridge, because everything it does is an order operation and
the orders module already depends on customers, catalog and inventory: no new module edge.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.modules.orders.models import Order
from app.modules.orders.routers._deps import get_db
from app.modules.orders.service import OrderService

router = APIRouter()


def _resolve_tenant_key(x_wp_key: str = Header(...)) -> UUID:
    """The tenant a per-tenant platform key belongs to (the same mapping the catalog bridge uses:
    ``WEBSITE_PLATFORM_TENANT_KEYS``). Unknown key, or a mapping value that is not a UUID, is 401:
    a misconfigured mapping fails loudly instead of serving some other tenant."""
    mapping = get_settings().website_platform_tenant_keys or {}
    tenant_id = mapping.get(x_wp_key)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid website-platform key"
        )
    try:
        return UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid website-platform key"
        ) from exc


_MAX_LINES = 50
_MAX_QTY = 1000


class WebsiteOrderLine(BaseModel):
    """One cart line. ``variant_id`` is the id the catalog endpoint gave the storefront."""

    model_config = ConfigDict(extra="forbid")

    variant_id: UUID
    quantity: int = Field(ge=1, le=_MAX_QTY)


class WebsiteOrderCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=5, max_length=31)
    email: str | None = Field(default=None, max_length=320)


class WebsiteOrderIn(BaseModel):
    """An order as the storefront knows it. There is deliberately no price field: ``extra=forbid``
    turns a storefront that tries to name one into a 422 instead of a silently ignored number."""

    model_config = ConfigDict(extra="forbid")

    external_ref: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    customer: WebsiteOrderCustomer
    items: list[WebsiteOrderLine] = Field(min_length=1, max_length=_MAX_LINES)
    shipping_address: dict[str, str] | None = None
    note: str | None = Field(default=None, max_length=500)


class WebsiteOrderOut(BaseModel):
    order_id: UUID
    number: str
    status: str
    currency: str
    subtotal: Decimal
    grand_total: Decimal
    # True when this ref had already been accepted and the stored order is returned unchanged.
    already_received: bool = False


def _order_out(order, *, already_received: bool) -> WebsiteOrderOut:
    return WebsiteOrderOut(
        order_id=order.id,
        number=order.number,
        status=order.status,
        currency=order.currency,
        subtotal=Decimal(str(order.subtotal)),
        grand_total=Decimal(str(order.grand_total)),
        already_received=already_received,
    )


@router.post("/website-platform/orders", response_model=WebsiteOrderOut)
async def website_platform_create_order(
    body: WebsiteOrderIn,
    key_tenant: UUID = Depends(_resolve_tenant_key),
    db: AsyncSession = Depends(get_db),
) -> WebsiteOrderOut:
    """Book a storefront order in Fihrist.

    Idempotent on ``external_ref``: a retry after a lost response returns the order the first call
    made (``already_received``) and reserves nothing a second time. The unique index on
    (tenant, channel, external_ref) is the guarantee; the lookup below is the fast path, and a
    concurrent twin that loses the race is turned back into that same lookup.
    """
    await bind_tenant(db, key_tenant)

    async def _existing() -> Order | None:
        return (
            await db.execute(
                select(Order).where(
                    Order.channel == "website", Order.external_ref == body.external_ref
                )
            )
        ).scalar_one_or_none()

    found = await _existing()
    if found is not None:
        return _order_out(found, already_received=True)

    customer = await OrderService.customer_for_channel_order(
        db, key_tenant, phone=body.customer.phone, name=body.customer.name, source="website"
    )
    if customer is None:
        # A number that is not a phone, or a customer the merchant has blocked. Same wording for
        # both: the storefront is not told which.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="this customer cannot place an order",
        )

    try:
        # A savepoint, so losing the unique-index race rolls back only this attempt.
        async with db.begin_nested():
            order = await OrderService.create_order(
                db,
                key_tenant,
                customer.id,
                [{"variant_id": str(i.variant_id), "quantity": i.quantity} for i in body.items],
                channel="website",
                shipping_address=body.shipping_address,
                note=body.note,
            )
            order.external_ref = body.external_ref
            await db.flush()
    except IntegrityError:
        twin = await _existing()
        if twin is None:
            raise
        return _order_out(twin, already_received=True)
    return _order_out(order, already_received=False)
