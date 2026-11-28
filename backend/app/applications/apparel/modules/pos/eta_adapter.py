"""Turn a till document (sale, return, exchange half) into an ETA e-receipt context.

The till records goods and values, and nothing else the authority needs: no tax, no payment
method, no registered item codes. This module is the ONE place that bridges the gap, and it never
invents what it cannot know:

* VAT: ``einvoice.prices_include_vat`` says whether shelf prices already carry it. The line's
  recorded NET (``OrderItem.total``) is the truth the customer paid, so VAT is derived FROM it and
  the receipt total equals the till total to the piastre.
* Payment: what the customer really paid (``OrderPayment``), as ONE code by the shop's
  ``einvoice.split_payment_rule``; ``einvoice.default_payment_method`` only when nothing was
  recorded (a sale on account, or a till that takes no payments).
* Item codes: ``ProductIdentifier`` rows of type ``egs`` / ``gs1``. A line without one makes the
  receipt wait with a precise reason; it is never sent with a made-up code.

Everything here is read-only. Whether and when the receipt is sent is ``delivery.py``'s business.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.catalog.models import ProductIdentifier
from app.applications.apparel.modules.einvoice.ports import EInvoiceContext, InvoiceLineItem, PartyInfo
from app.applications.apparel.modules.einvoice.providers.eta.calc import price_excluding_vat, q5
from app.applications.apparel.modules.einvoice.providers.eta.codes import UNIT_EACH, payment_method_for_tender

logger = logging.getLogger(__name__)

# The merchant picks the category; the authority's sub-type code for it is fixed by the authority.
_VAT_SUBTYPE = {"taxable": "V009", "exempt": "V003", "non_taxable": "V004"}
_HUNDRED = Decimal(100)


class NotReady(ValueError):
    """The till document cannot become an ETA receipt yet; the message says exactly why."""


@dataclass(frozen=True)
class EtaSettings:
    """Everything about the shop itself that the merchant decides (Settings > e-receipt)."""

    enabled: bool
    prices_include_vat: bool
    default_payment_method: str
    vat_category: str = "taxable"
    unit_code: str = UNIT_EACH
    delivery_mode: str = "FC"
    warn_hours_before_deadline: int = 24
    split_payment_rule: str = "largest"
    settings_confirmed: bool = False


async def eta_settings(session: AsyncSession, tenant_id: uuid.UUID) -> EtaSettings:
    from app.modules.settings.service import SettingsService

    svc = SettingsService(session, tenant_id)
    return EtaSettings(
        enabled=bool(await svc.value("einvoice.eta_enabled")),
        prices_include_vat=bool(await svc.value("einvoice.prices_include_vat")),
        default_payment_method=str(await svc.value("einvoice.default_payment_method")),
        vat_category=str(await svc.value("einvoice.vat_category")),
        unit_code=str(await svc.value("einvoice.unit_code")),
        delivery_mode=str(await svc.value("einvoice.delivery_mode")),
        warn_hours_before_deadline=int(await svc.value("einvoice.warn_hours_before_deadline")),
        split_payment_rule=str(await svc.value("einvoice.split_payment_rule")),
        settings_confirmed=bool(await svc.value("einvoice.settings_confirmed")),
    )


async def eta_branch(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """The store's registered branch, exactly as the merchant typed it (never defaulted)."""
    from app.modules.settings.service import SettingsService

    svc = SettingsService(session, tenant_id)
    return {
        "branch_code": str(await svc.value("einvoice.branch_code") or ""),
        "activity_code": str(await svc.value("einvoice.activity_code") or ""),
        "branch_address": {
            "governate": str(await svc.value("einvoice.branch_governate") or ""),
            "region_city": str(await svc.value("einvoice.branch_region_city") or ""),
            "street": str(await svc.value("einvoice.branch_street") or ""),
            "building_number": str(await svc.value("einvoice.branch_building_number") or ""),
        },
    }


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
        unit_code=settings.unit_code,
        vat_subtype=_VAT_SUBTYPE[settings.vat_category],
    )


def effective_rate(settings: EtaSettings, national_rate: Decimal) -> Decimal:
    """VAT actually charged: the national rate only for taxable goods, zero otherwise."""
    return national_rate if settings.vat_category == "taxable" else Decimal("0.00")


async def _sold_before_adoption(
    session: AsyncSession, tenant_id: uuid.UUID, sold_at: datetime | None
) -> bool:
    """Was this sale made before the shop's first e-receipt? That moment is when it joined.

    Taken from the shop's own history (its earliest e-receipt), never guessed. A shop with no
    e-receipt at all has not joined, so nothing it sold counts as "before"."""
    from sqlalchemy import func

    from app.applications.apparel.modules.einvoice.models import EInvoiceDocument

    if sold_at is None:
        return False
    first = (
        await session.execute(
            select(func.min(EInvoiceDocument.issued_at)).where(
                EInvoiceDocument.tenant_id == tenant_id,
                EInvoiceDocument.provider_type == "eta",
            )
        )
    ).scalar_one_or_none()
    return first is not None and sold_at < first


async def vat_rate_percent(session: AsyncSession, issued_at: datetime) -> Decimal:
    """Egypt's VAT on the issue date, from the shared tax table (never a literal here)."""
    from app.modules.billing.services.tax import resolve_applicable_tax_rate

    fraction = await resolve_applicable_tax_rate(session, "EG", as_of_date=issued_at.date())
    if fraction is None:
        raise NotReady("no VAT rate is configured for Egypt on the issue date")
    return (fraction * _HUNDRED).quantize(Decimal("0.01"))


# When two codes tie on money, the one a person would call the "main" way wins: never chance.
_TIE_ORDER = ("C", "V")


def payment_method_for(lines, *, rule: str, fallback: str) -> str:
    """The ONE ETA payment code for a sale paid in one or more lines.

    ``lines`` are ``(till_method, amount)`` pairs. Each is translated to the authority's code
    first (a wallet and a bank transfer are both ``O``), the amounts of lines sharing a code are
    added, and then the shop's rule picks the winner:

    * ``largest``: the code that took the most money.
    * ``cash_first``: cash whenever any cash was taken, otherwise the largest.

    An exact tie goes cash, then card, then the code that sorts first, so the answer never
    depends on the order the lines were typed. With no line at all the shop's own default
    ``fallback`` is used: that is a sale on account, or a till that takes no payments.
    """
    totals: dict[str, Decimal] = {}
    for method, amount in lines:
        code = str(payment_method_for_tender(method).value)
        totals[code] = totals.get(code, Decimal(0)) + Decimal(str(amount))
    if not totals:
        return fallback
    if rule == "cash_first" and totals.get("C", Decimal(0)) > 0:
        return "C"

    def rank(code: str) -> tuple:
        tie = _TIE_ORDER.index(code) if code in _TIE_ORDER else len(_TIE_ORDER)
        return (-totals[code], tie, code)

    return min(totals, key=rank)


async def _paid_lines(session: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID) -> list:
    """What the customer actually paid on this order: only money that was really captured."""
    from app.applications.apparel.modules.orders.service import OrderService

    return [
        (p.method, p.amount)
        for p in await OrderService.list_payments(session, tenant_id, order_id, limit=200)
        if p.status == "captured"
    ]


async def build_context(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    receipt,
    *,
    now: datetime | None = None,
) -> EInvoiceContext:
    """The ETA context for one till receipt (``PosReceipt``). Raises :class:`NotReady`."""
    from app.applications.apparel.modules.einvoice.models import EInvoiceDocument
    from app.applications.apparel.modules.orders.models import Order, OrderItem
    from app.applications.apparel.modules.pos.models import PosReceipt, PosReturnLine

    settings = await eta_settings(session, tenant_id)
    issued_at = receipt.issued_at or now or datetime.now(UTC)
    rate = effective_rate(settings, await vat_rate_percent(session, issued_at))
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
    reference_less = False
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
        if ref:
            original_uuid = ref
        elif await _sold_before_adoption(session, tenant_id, sold_at):
            # The authority has a type for exactly this: goods sold before the shop joined the
            # system. It carries no reference, only the reason "B".
            reference_less = True
        else:
            raise NotReady(
                f"the original sale {sale.number} has no e-receipt to refer to, and it was not "
                "sold before this shop started issuing e-receipts"
            )
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
            **{k: v for k, v in r.items() if k != "variant_id"},
        )
        for r in raw
    ]
    subtotal = q5(sum((line.subtotal for line in lines), Decimal(0)))
    tax_total = q5(sum((line.tax_amount for line in lines), Decimal(0)))
    extras: dict = {
        "payment_method": payment_method_for(
            await _paid_lines(session, tenant_id, receipt.order_id),
            rule=settings.split_payment_rule,
            fallback=settings.default_payment_method,
        ),
        "delivery_mode": settings.delivery_mode,
        "store_profile": await eta_branch(session, tenant_id),
    }
    document_type = "sale_receipt"
    if receipt.kind == "return":
        document_type = "return_receipt"
        extras["sales_issued_at"] = sold_at
        extras["return_reason"] = None
        if reference_less:
            document_type = "return_without_reference"
            extras["return_reason"] = "B"  # sold before the shop joined the system
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
        original_reference=None if reference_less else original_number,
        original_uuid=original_uuid,
        extras=extras,
    )


@dataclass(frozen=True)
class HookResult:
    """What the cashier hook did for one receipt. ``skipped`` carries the reason, never raised."""

    issued: bool
    skipped: str | None = None


async def issue_for_receipt(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    receipt,
    *,
    register_code: str,
) -> HookResult:
    """Issue the ETA e-receipt for a till receipt. NEVER raises into the sale.

    A customer is standing at the counter. Whatever is missing on the e-receipt side (the till is
    not set up, an item has no registered code, the store has no tax number yet) must never stop
    the sale, so every failure is caught here, recorded as a warning and left for the owner to
    fix. The work runs in a savepoint, so even a database error cannot poison the sale's own
    transaction.

    The ETA till is the one whose serial equals the register's code, and it is never created
    here: it must be set up deliberately with the store's real registration data.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.errors import DomainError
    from app.applications.apparel.modules.einvoice.models import EInvoiceDevice
    from app.applications.apparel.modules.einvoice.providers.eta.client import EtaError
    from app.applications.apparel.modules.einvoice.service import EInvoiceService

    try:
        shop = await eta_settings(session, tenant_id)
        if not shop.enabled:
            return HookResult(False, "disabled")
        if not shop.settings_confirmed:
            return HookResult(
                False,
                "the merchant has not confirmed the price, VAT and payment settings "
                "(einvoice.settings_confirmed): confirm them to start issuing",
            )
        device = (
            await session.execute(
                select(EInvoiceDevice).where(
                    EInvoiceDevice.tenant_id == tenant_id,
                    EInvoiceDevice.device_serial == register_code,
                    EInvoiceDevice.provider_type == "eta",
                    EInvoiceDevice.status == "active",
                )
            )
        ).scalar_one_or_none()
        if device is None:
            return HookResult(False, f"no active ETA till for register {register_code}")
        async with session.begin_nested():
            context = await build_context(session, tenant_id, receipt)
            await EInvoiceService.issue_einvoice(
                session,
                tenant_id,
                context,
                device_id=device.id,
                order_id=receipt.order_id,
                receipt_id=receipt.id,
            )
        return HookResult(True)
    except NotReady as exc:
        logger.warning("eta.hook.not_ready tenant=%s receipt=%s: %s", tenant_id, receipt.id, exc)
        return HookResult(False, str(exc))
    except (SQLAlchemyError, DomainError, EtaError, ValueError, KeyError, LookupError) as exc:
        logger.warning(
            "eta.hook.failed tenant=%s receipt=%s: %s", tenant_id, receipt.id, type(exc).__name__
        )
        return HookResult(False, f"{type(exc).__name__}")
