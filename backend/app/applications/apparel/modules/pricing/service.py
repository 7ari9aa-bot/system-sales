"""Pricing: which price applies, and what comes off it.

The resolver is the point of this module. A shop can hold a product's own price history, several
named price lists and a set of running offers, and the till still has to answer one number. So
everything here funnels through :meth:`PricingService.resolve` and :meth:`PricingService.quote`,
and both read their policy from the settings engine rather than hard-coding a rule.

Order of resolution, and why:

1. If price lists are off (``pricing.price_lists_enabled``), the product's own price stands. The
   lists stay in the database untouched, so turning the switch back on restores them.
2. Otherwise the best live list wins: a list inside its date window, active, highest priority,
   then the default one, then the lowest price for the customer. A tie is broken in the
   customer's favour, never by insertion order.
3. Quantity tiers apply only when ``pricing.quantity_tiers_enabled``; the tier is the highest
   ``min_quantity`` the line reaches.
4. ``pricing.round_prices_to`` rounds the final unit price, never an intermediate step, so the
   rounding cannot compound across tiers.

Discounts are applied to a QUOTE, not stored on a rule: the same rule on a different basket
gives a different number, and storing the number would make the rule lie as soon as anything
changed. ``pricing.stacked_discounts`` decides whether more than one rule may apply; when it is
off the single best rule wins. ``pricing.max_order_discount_pct`` is a ceiling on the whole
quote, and a rule's own ``max_discount`` caps that rule. Both clamp rather than refuse: a smaller
discount than promised is a smaller problem than a sale that cannot be completed.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.applications.apparel.modules.pricing.models import (
    DISCOUNT_KINDS,
    DISCOUNT_SCOPES,
    DiscountRule,
    PriceList,
    PriceListItem,
)

# The settings this module reads. Kept literal so the settings guard sees them.
_KEYS = (
    "pricing.price_lists_enabled",
    "pricing.quantity_tiers_enabled",
    "pricing.round_prices_to",
    "pricing.allow_price_below_cost",
    "pricing.auto_apply_offers",
    "pricing.stacked_discounts",
    "pricing.max_order_discount_pct",
)

_CENTS = Decimal("0.01")


def _money(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _round_to(value: Decimal, step: str) -> Decimal:
    """Round a price to the step the owner chose. "none" leaves it exactly as resolved."""
    if step not in {"0.25", "0.5", "1"}:
        return value.quantize(_CENTS, rounding=ROUND_HALF_UP)
    unit = Decimal(step)
    return (value / unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unit


class PricingService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def _settings(self) -> dict:
        # Function scope: importing another module's service at module scope is what the boundary
        # guard counts, and pricing is not allowed to add to it.
        from app.modules.settings.service import SettingsService

        return await SettingsService(self.session, self.tenant_id).resolve_many(list(_KEYS))

    # ----------------------------------------------------------------- price lists

    async def list_price_lists(self) -> list[PriceList]:
        rows = await self.session.execute(
            select(PriceList)
            .where(PriceList.tenant_id == self.tenant_id)
            .order_by(PriceList.priority.desc(), PriceList.name)
        )
        return list(rows.scalars())

    async def create_price_list(
        self,
        *,
        name: str,
        code: str,
        currency: str = "EGP",
        priority: int = 0,
        is_default: bool = False,
        valid_from: date | None = None,
        valid_to: date | None = None,
        notes: str | None = None,
    ) -> PriceList:
        name = (name or "").strip()
        code = (code or "").strip().upper()
        if not name or not code:
            raise ValidationError("A price list needs a name and a code")
        if valid_from and valid_to and valid_to < valid_from:
            raise ValidationError("A price list cannot end before it starts")
        if is_default:
            await self._clear_default()
        row = PriceList(
            tenant_id=self.tenant_id,
            name=name,
            code=code,
            currency=(currency or "EGP").upper()[:3],
            priority=int(priority),
            is_default=is_default,
            valid_from=valid_from,
            valid_to=valid_to,
            notes=notes,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _clear_default(self) -> None:
        """Only one list may be the default; the newest choice wins."""
        rows = await self.session.execute(
            select(PriceList).where(
                PriceList.tenant_id == self.tenant_id, PriceList.is_default.is_(True)
            )
        )
        for row in rows.scalars():
            row.is_default = False

    async def archive_price_list(self, list_id: uuid.UUID) -> PriceList:
        row = await self._list_or_404(list_id)
        row.status = "archived"
        row.is_default = False
        await self.session.flush()
        return row

    async def _list_or_404(self, list_id: uuid.UUID) -> PriceList:
        row = await self.session.get(PriceList, list_id)
        if row is None or row.tenant_id != self.tenant_id:
            raise ValidationError("Price list not found")
        return row

    async def list_items(self, list_id: uuid.UUID) -> list[PriceListItem]:
        await self._list_or_404(list_id)
        rows = await self.session.execute(
            select(PriceListItem)
            .where(PriceListItem.price_list_id == list_id)
            .order_by(PriceListItem.variant_id, PriceListItem.min_quantity)
        )
        return list(rows.scalars())

    async def set_item(
        self,
        *,
        list_id: uuid.UUID,
        variant_id: uuid.UUID,
        unit_price: Decimal | str | int,
        min_quantity: int = 1,
    ) -> PriceListItem:
        """Put one price in one list. The same (list, variant, tier) is replaced, not duplicated."""
        await self._list_or_404(list_id)
        price = _money(unit_price)
        if price is None or price < 0:
            raise ValidationError("A price must be a number of zero or more")
        if int(min_quantity) < 1:
            raise ValidationError("A quantity tier starts at 1")
        rows = await self.session.execute(
            select(PriceListItem).where(
                PriceListItem.price_list_id == list_id,
                PriceListItem.variant_id == variant_id,
                PriceListItem.min_quantity == int(min_quantity),
            )
        )
        row = rows.scalars().first()
        if row is None:
            row = PriceListItem(
                tenant_id=self.tenant_id,
                price_list_id=list_id,
                variant_id=variant_id,
                unit_price=price,
                min_quantity=int(min_quantity),
            )
            self.session.add(row)
        else:
            row.unit_price = price
        await self.session.flush()
        return row

    # ----------------------------------------------------------------- discount rules

    async def list_discount_rules(self) -> list[DiscountRule]:
        rows = await self.session.execute(
            select(DiscountRule)
            .where(DiscountRule.tenant_id == self.tenant_id)
            .order_by(DiscountRule.priority.desc(), DiscountRule.name)
        )
        return list(rows.scalars())

    async def create_discount_rule(
        self,
        *,
        name: str,
        kind: str,
        value: Decimal | str | int,
        scope: str = "order",
        target_id: uuid.UUID | None = None,
        code: str | None = None,
        min_subtotal: Decimal | str | int | None = None,
        max_discount: Decimal | str | int | None = None,
        requires_code: bool = False,
        priority: int = 0,
        starts_on: date | None = None,
        ends_on: date | None = None,
    ) -> DiscountRule:
        name = (name or "").strip()
        if not name:
            raise ValidationError("An offer needs a name")
        if kind not in DISCOUNT_KINDS:
            raise ValidationError("An offer is either a percentage or an amount")
        if scope not in DISCOUNT_SCOPES:
            raise ValidationError("An offer applies to the order, a category or a variant")
        if scope != "order" and target_id is None:
            raise ValidationError("Say which category or variant the offer applies to")
        if scope == "order" and target_id is not None:
            raise ValidationError("An order-wide offer does not name a target")
        amount = _money(value)
        if amount is None or amount < 0:
            raise ValidationError("A discount must be a number of zero or more")
        if kind == "percent" and amount > 100:
            raise ValidationError("A percentage discount cannot exceed 100")
        if starts_on and ends_on and ends_on < starts_on:
            raise ValidationError("An offer cannot end before it starts")
        if requires_code and not (code or "").strip():
            raise ValidationError("An offer that requires a code needs one")
        row = DiscountRule(
            tenant_id=self.tenant_id,
            name=name,
            code=(code or "").strip().upper() or None,
            kind=kind,
            value=amount,
            scope=scope,
            target_id=target_id,
            min_subtotal=_money(min_subtotal),
            max_discount=_money(max_discount),
            requires_code=requires_code,
            priority=int(priority),
            starts_on=starts_on,
            ends_on=ends_on,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def set_rule_status(self, rule_id: uuid.UUID, status: str) -> DiscountRule:
        if status not in {"active", "archived"}:
            raise ValidationError("A rule is either active or archived")
        row = await self.session.get(DiscountRule, rule_id)
        if row is None or row.tenant_id != self.tenant_id:
            raise ValidationError("Offer not found")
        row.status = status
        await self.session.flush()
        return row

    # ----------------------------------------------------------------- resolution

    async def resolve(
        self,
        *,
        variant_id: uuid.UUID,
        base_price: Decimal | str | int,
        quantity: int = 1,
        on_date: date | None = None,
    ) -> dict:
        """The unit price that applies, and where it came from."""
        resolved = await self._settings()
        values = {k: r.value for k, r in resolved.items()}
        base = _money(base_price) or Decimal("0.00")
        quantity = max(1, int(quantity))
        today = on_date or date.today()

        source = "product"
        price = base
        list_id: uuid.UUID | None = None

        if bool(values.get("pricing.price_lists_enabled")):
            best = await self._best_item(variant_id, quantity, today, values)
            if best is not None:
                price = best.unit_price
                list_id = best.price_list_id
                source = "price_list"

        if source == "product" and bool(values.get("pricing.quantity_tiers_enabled")):
            tier = await self._product_tier(variant_id, quantity)
            if tier is not None:
                price = tier
                source = "quantity_tier"

        price = _round_to(price, str(values.get("pricing.round_prices_to") or "none"))
        return {
            "variant_id": variant_id,
            "quantity": quantity,
            "unit_price": price,
            "price_list_id": list_id,
            "source": source,
            "base_price": base,
        }

    async def _best_item(
        self, variant_id: uuid.UUID, quantity: int, today: date, values: dict
    ) -> PriceListItem | None:
        rows = await self.session.execute(
            select(PriceListItem, PriceList)
            .join(PriceList, PriceList.id == PriceListItem.price_list_id)
            .where(
                PriceListItem.tenant_id == self.tenant_id,
                PriceListItem.variant_id == variant_id,
                PriceListItem.min_quantity <= quantity,
                PriceList.status == "active",
            )
            .order_by(PriceList.priority.desc(), PriceListItem.unit_price)
        )
        tiers = bool(values.get("pricing.quantity_tiers_enabled"))
        candidates = []
        for item, plist in rows.all():
            if plist.valid_from and plist.valid_from > today:
                continue
            if plist.valid_to and plist.valid_to < today:
                continue
            candidates.append((item, plist))
        if not candidates:
            return None
        if tiers:
            # Highest tier reached wins, then the cheapest, then the default list.
            candidates.sort(
                key=lambda p: (-p[0].min_quantity, p[0].unit_price, not p[1].is_default)
            )
        else:
            candidates.sort(key=lambda p: (p[0].unit_price, not p[1].is_default))
        return candidates[0][0]

    async def _product_tier(self, variant_id: uuid.UUID, quantity: int) -> Decimal | None:
        """The variant's own ladder at this quantity, read through the catalogue's service.

        §8: a domain service never imports another module's models. The catalogue already
        publishes the ladder (``price_tiers_for_many``) together with the rule that a tier is
        only ever read in the tenant's own currency, so this asks it rather than reaching into
        ``product_prices``. The previous query had no currency filter, which meant a tenant that
        ever changed currency could be quoted from a ladder it can no longer sell.
        """
        from app.core.tenancy import resolve_tenant_currency
        from app.applications.apparel.modules.catalog.services import CatalogService

        currency = await resolve_tenant_currency(self.session, self.tenant_id)
        ladders = await CatalogService.price_tiers_for_many(
            self.session, self.tenant_id, [variant_id], currency=currency
        )
        for min_quantity, unit_price in ladders.get(variant_id) or []:
            if min_quantity <= quantity:
                return unit_price
        return None

    async def quote(
        self,
        *,
        lines: list[dict],
        code: str | None = None,
        on_date: date | None = None,
    ) -> dict:
        """What the order costs after the offers that are allowed to run today.

        ``lines`` are dicts with ``variant_id``, ``unit_price``, ``quantity`` and optionally
        ``category_id``. The reply carries the discount per rule so the till can show why.
        """
        resolved = await self._settings()
        values = {k: r.value for k, r in resolved.items()}
        today = on_date or date.today()

        subtotal = sum(
            (_money(ln.get("unit_price")) or Decimal("0")) * int(ln.get("quantity", 1))
            for ln in lines
        )
        subtotal = subtotal.quantize(_CENTS, rounding=ROUND_HALF_UP)

        rules = await self.list_discount_rules()
        applies: list[dict] = []
        wanted = (code or "").strip().upper()
        for rule in rules:
            if rule.status != "active":
                continue
            if rule.starts_on and rule.starts_on > today:
                continue
            if rule.ends_on and rule.ends_on < today:
                continue
            if rule.requires_code and (rule.code or "") != wanted:
                continue
            if rule.min_subtotal is not None and subtotal < rule.min_subtotal:
                continue
            base = self._scope_amount(rule, lines, subtotal)
            if base <= 0:
                continue
            amount = base * rule.value / Decimal("100") if rule.kind == "percent" else rule.value
            if rule.max_discount is not None:
                amount = min(amount, rule.max_discount)
            amount = min(amount, base).quantize(_CENTS, rounding=ROUND_HALF_UP)
            if amount <= 0:
                continue
            applies.append(
                {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "code": rule.code,
                    "amount": amount,
                    "priority": rule.priority,
                }
            )

        if not bool(values.get("pricing.auto_apply_offers")):
            # Without auto-apply, only an offer the customer asked for by code runs.
            applies = [a for a in applies if a["code"] and a["code"] == wanted]

        applies.sort(key=lambda a: (-a["priority"], -a["amount"]))
        if not bool(values.get("pricing.stacked_discounts")):
            applies = applies[:1]

        discount = sum((a["amount"] for a in applies), Decimal("0.00"))
        ceiling_pct = _money(values.get("pricing.max_order_discount_pct")) or Decimal("0")
        ceiling = (subtotal * ceiling_pct / Decimal("100")).quantize(_CENTS, rounding=ROUND_HALF_UP)
        capped = False
        if ceiling > 0 and discount > ceiling:
            discount = ceiling
            capped = True
        discount = min(discount, subtotal)

        return {
            "subtotal": subtotal,
            "discount": discount,
            "total": (subtotal - discount).quantize(_CENTS, rounding=ROUND_HALF_UP),
            "applied": applies,
            "capped": capped,
            "allows_below_cost": bool(values.get("pricing.allow_price_below_cost")),
        }

    @staticmethod
    def _scope_amount(rule: DiscountRule, lines: list[dict], subtotal: Decimal) -> Decimal:
        """The money a rule is allowed to work on: the whole order, or the lines it names."""
        if rule.scope == "order":
            return subtotal
        key = "category_id" if rule.scope == "category" else "variant_id"
        total = Decimal("0")
        for line in lines:
            if str(line.get(key)) != str(rule.target_id):
                continue
            total += (_money(line.get("unit_price")) or Decimal("0")) * int(line.get("quantity", 1))
        return total
