"""Turn a till document (sale, return, exchange half) into an ETA e-receipt context.

The till records goods and values, and nothing else the authority needs: no tax, no payment
method, no registered item codes. This module is the ONE place that bridges the gap, and it never
invents what it cannot know:

* VAT: ``einvoice.prices_include_vat`` says whether shelf prices already carry it. The line's
  recorded NET (``OrderItem.total``) is the truth the customer paid, so VAT is derived FROM it and
  the receipt total equals the till total to the piastre.
* Payment: ``einvoice.default_payment_method`` (the till does not ask how the customer paid).
* Item codes: ``ProductIdentifier`` rows of type ``egs`` / ``gs1``. A line without one makes the
  receipt wait with a precise reason; it is never sent with a made-up code.

Everything here is read-only. Whether and when the receipt is sent is ``delivery.py``'s business.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductIdentifier
from app.modules.einvoice.ports import EInvoiceContext, InvoiceLineItem, PartyInfo
from app.modules.einvoice.providers.eta.calc import price_excluding_vat, q5
from app.modules.einvoice.providers.eta.codes import UNIT_EACH

_VAT_SUBTYPE_TAXABLE = "V009"
_HUNDRED = Decimal(100)


class NotReady(ValueError):
    """The till document cannot become an ETA receipt yet; the message says exactly why."""


@dataclass(frozen=True)
class EtaSettings:
    enabled: bool
    prices_include_vat: bool
    default_payment_method: str


async def eta_settings(session: AsyncSession, tenant_id: uuid.UUID) -> EtaSettings:
    from app.modules.settings.service import SettingsService

    svc = SettingsService(session, tenant_id)
    return EtaSettings(
        enabled=bool(await svc.value("einvoice.eta_enabled")),
        prices_include_vat=bool(await svc.value("einvoice.prices_include_vat")),
        default_payment_method=str(await svc.value("einvoice.default_payment_method")),
    )


async def _seller(session: AsyncSession, tenant_id: uuid.UUID) -> PartyInfo:
    from app.modules.settings.service import SettingsService

    svc = SettingsService(session, tenant_id)
    name = (await svc.value("business.legal_name")) or (await svc.value("business.trade_name"))
    tax_id = await svc.value("business.tax_id")
    if not tax_id:
        raise NotReady("the store's tax registration number (business.tax_id) is not set")
    if not name:
        raise NotReady("the store's registered name (business.legal_name) is not set")
    return PartyInfo(name=str(name), tax_id=str(tax_id), country_code="EG")


async def _item_codes(
    session: AsyncSession, tenant_id: uuid.UUID, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    """variant -> (item type, code). EGS wins over GS1 when both exist (it is the one the
    authority registered for this taxpayer)."""
    rows = (
        await session.execute(
            select(
                ProductIdentifier.variant_id, ProductIdentifier.type, ProductIdentifier.value
            ).where(
                ProductIdentifier.tenant_id == tenant_id,
                ProductIdentifier.variant_id.in_(variant_ids),
                ProductIdentifier.type.in_(("egs", "gs1")),
            )
        )
    ).all()
    found: dict[uuid.UUID, tuple[str, str]] = {}
    for variant_id, kind, value in sorted(rows, key=lambda r: r.type != "egs"):
        found.setdefault(variant_id, (kind.upper(), value))
    return found


def split_line(
    net_paid: Decimal,
    quantity: int,
    gross_unit_price: Decimal,
    *,
    includes_vat: bool,
    rate: Decimal,
) -> tuple[Decimal, Decimal]:
    """(unit price before VAT and before discount, discount amount before VAT) for one line.

    ``net_paid`` is what the customer paid for the line (after the till's discount). The pair is
    chosen so ETA's own equations reproduce ``net_paid`` exactly: sale = unit x qty,
    net = sale - discount, vat = net x rate, total = net + vat.
    """
    if includes_vat:
        unit = price_excluding_vat(gross_unit_price, rate)
        net_before_vat = q5(net_paid / (Decimal(1) + rate / _HUNDRED))
    else:
        unit = q5(gross_unit_price)
        net_before_vat = q5(net_paid)
    discount = q5(unit * quantity - net_before_vat)
    return unit, max(discount, Decimal(0))


def _line(
    *,
    title: str,
    sku: str | None,
    quantity: int,
    gross_unit_price: Decimal,
    net_paid: Decimal,
    code: tuple[str, str] | None,
    settings: EtaSettings,
    rate: Decimal,
) -> InvoiceLineItem:
    if code is None:
        raise NotReady(
            f"{sku or title}: no registered item code (add an 'egs' or 'gs1' identifier)"
        )
    unit, discount = split_line(
        net_paid,
        quantity,
        gross_unit_price,
        includes_vat=settings.prices_include_vat,
        rate=rate,
    )
    sale = q5(unit * quantity)
    net = q5(sale - discount)
    vat = q5(net * rate / _HUNDRED)
    return InvoiceLineItem(
        item_name=title,
        quantity=Decimal(quantity),
        unit_price=unit,
        discount=discount,
        subtotal=net,
        tax_rate=q5(rate / _HUNDRED),
        tax_amount=vat,
        total=q5(net + vat),
        sku=sku or "",
        item_code_type=code[0],
        item_code=code[1],
        unit_code=UNIT_EACH,
        vat_subtype=_VAT_SUBTYPE_TAXABLE,
    )


async def vat_rate_percent(session: AsyncSession, issued_at: datetime) -> Decimal:
    """Egypt's VAT on the issue date, from the shared tax table (never a literal here)."""
    from app.modules.billing.services.tax import resolve_applicable_tax_rate

    fraction = await resolve_applicable_tax_rate(session, "EG", as_of_date=issued_at.date())
    if fraction is None:
        raise NotReady("no VAT rate is configured for Egypt on the issue date")
    return (fraction * _HUNDRED).quantize(Decimal("0.01"))


async def build_context(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    receipt,
    *,
    now: datetime | None = None,
) -> EInvoiceContext:
    """The ETA context for one till receipt (``PosReceipt``). Raises :class:`NotReady`."""
    from app.modules.einvoice.models import EInvoiceDocument
    from app.modules.orders.models import Order, OrderItem
    from app.modules.pos.models import PosReceipt, PosReturnLine

    settings = await eta_settings(session, tenant_id)
    issued_at = receipt.issued_at or now or datetime.now(UTC)
    rate = await vat_rate_percent(session, issued_at)
    seller = await _seller(session, tenant_id)
    order = (
        await session.execute(
            select(Order).where(Order.tenant_id == tenant_id, Order.id == receipt.order_id)
        )
    ).scalar_one()

    raw: list[dict] = []
    original_number: str | None = None
    original_uuid: str | None = None
    sold_at: datetime | None = None
    if receipt.kind == "return":
        sale = (
            await session.execute(
                select(PosReceipt)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.order_id == receipt.order_id,
                    PosReceipt.kind == "sale",
                )
                .order_by(PosReceipt.issued_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if sale is None:
            raise NotReady("the original sale receipt of this return was not found")
        original_number, sold_at = sale.number, sale.issued_at
        ref = (
            await session.execute(
                select(EInvoiceDocument.invoice_hash).where(
                    EInvoiceDocument.tenant_id == tenant_id,
                    EInvoiceDocument.invoice_number == sale.number,
                )
            )
        ).scalar_one_or_none()
        if not ref:
            raise NotReady(
                f"the original sale {sale.number} has no e-receipt to refer to "
                "(a return needs one: it cannot be sent as a return with a reference)"
            )
        original_uuid = ref
        originals = {
            r.variant_id: r
            for r in (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id, OrderItem.order_id == receipt.order_id
                    )
                )
            ).scalars()
        }
        for rl in (
            await session.execute(
                select(PosReturnLine).where(
                    PosReturnLine.tenant_id == tenant_id, PosReturnLine.receipt_id == receipt.id
                )
            )
        ).scalars():
            item = originals[rl.variant_id]
            raw.append(
                {
                    "variant_id": rl.variant_id,
                    "title": item.title,
                    "sku": item.sku,
                    "quantity": int(rl.quantity),
                    "gross_unit_price": Decimal(str(rl.unit_price)),
                    "net_paid": Decimal(str(rl.refund_total)),
                }
            )
    else:
        for item in (
            await session.execute(
                select(OrderItem).where(
                    OrderItem.tenant_id == tenant_id, OrderItem.order_id == receipt.order_id
                )
            )
        ).scalars():
            raw.append(
                {
                    "variant_id": item.variant_id,
                    "title": item.title,
                    "sku": item.sku,
                    "quantity": int(item.quantity),
                    "gross_unit_price": Decimal(str(item.unit_price)),
                    "net_paid": Decimal(str(item.total)),
                }
            )
    if not raw:
        raise NotReady("the till document has no lines")

    codes = await _item_codes(session, tenant_id, [r["variant_id"] for r in raw])
    lines = [
        _line(
            code=codes.get(r["variant_id"]),
            settings=settings,
            rate=rate,
            variant=None,
            **{k: v for k, v in r.items() if k != "variant_id"},
        )
        for r in raw
    ]
    subtotal = q5(sum((line.subtotal for line in lines), Decimal(0)))
    tax_total = q5(sum((line.tax_amount for line in lines), Decimal(0)))
    extras: dict = {"payment_method": settings.default_payment_method}
    document_type = "sale_receipt"
    if receipt.kind == "return":
        document_type = "return_receipt"
        extras["sales_issued_at"] = sold_at
        extras["return_reason"] = None
    return EInvoiceContext(
        tenant_id=tenant_id,
        country_code="EG",
        document_type=document_type,
        invoice_number=receipt.number,
        issued_at=issued_at,
        seller=seller,
        currency=order.currency or "EGP",
        lines=lines,
        subtotal=subtotal,
        tax_total=tax_total,
        grand_total=q5(subtotal + tax_total),
        original_reference=original_number,
        original_uuid=original_uuid,
        extras=extras,
    )
