"""POS domain service — the sell flow and the cash-drawer truth (§189).

The POS says "make me a sale"; it never says "decrement stock". Every sell is
CreateOrder → capture payment → the §140 reservation machinery settles the
stock, exactly as a WhatsApp order would. This module owns profiles, registers,
sessions, cash rows, receipts and the per-method close reconciliation.

The scan path is the §179 entry point — a barcode (or any identifier) resolves
through ``CatalogService.resolve_identifier`` to exactly one active variant, and
the POS prices it with ``CatalogService.price_for``. A scan never invents a
product or a price.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.modules.orders.money import compute_totals, to_money
from app.modules.pos.models import (
    PosCashMovement,
    PosDailySales,
    PosHeldCart,
    PosProfile,
    PosReceipt,
    PosRegister,
    PosReturnLine,
    PosSession,
    PosSessionFloat,
    PosSessionHandover,
    PosSessionReconciliation,
)
from app.modules.pos.profiles import PosProfileService

_MANUAL_CASH_REASONS = {"pay_in", "pay_out", "cash_drop", "float_adjust"}
# Written only by the sell flow — a hand-written cash_sale would book money
# no order claims, the same lie a hand-written inventory `hold` would tell.
_SALE_ONLY_CASH_REASONS = {"cash_sale", "cash_refund"}
_CASH_DIRECTIONS = {"in", "out"}
_SALE_METHODS = {"cash", "card", "wallet", "bank_transfer"}
_NUMBER_ATTEMPTS = 3


def _positive_amount(value: object, field: str) -> Decimal:
    amount = to_money(value, field)
    if amount <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    return amount


def _float_amount(value: object, field: str) -> Decimal:
    """A drawer float may be zero, never negative."""
    amount = to_money(value, field)
    if amount < 0:
        raise ValidationError(f"{field} must not be negative")
    return amount


class PosService:
    """All POS rules; static methods taking (session, tenant_id), flush-only."""

    # --------------------------------------------------------- registers ----

    @staticmethod
    async def create_register(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        code: str,
        warehouse_id: UUID,
        profile_id: UUID | None = None,
    ) -> PosRegister:
        from app.modules.inventory.service import InventoryService

        cleaned_code = str(code).strip()
        if not cleaned_code or len(cleaned_code) > 31:
            raise ValidationError("register code must be 1-31 characters")
        await InventoryService.get_warehouse(session, tenant_id, warehouse_id)
        if profile_id is not None:
            profile = await PosProfileService.get(session, tenant_id, profile_id)
            # One rule: the register's warehouse is the one it sells from, and a profile's
            # register must agree with the profile, so the grid, the scan and the sale all see
            # the same stock.
            if profile.warehouse_id != warehouse_id:
                raise ValidationError(
                    "this register's warehouse must be the warehouse of its POS profile"
                )
        register = PosRegister(
            tenant_id=tenant_id,
            name=str(name).strip() or cleaned_code,
            code=cleaned_code,
            warehouse_id=warehouse_id,
            profile_id=profile_id,
        )
        session.add(register)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"register code '{cleaned_code}' already exists") from None
        return register

    @staticmethod
    async def list_registers(session: AsyncSession, tenant_id: UUID) -> list[PosRegister]:
        rows = (
            (
                await session.execute(
                    select(PosRegister)
                    .where(PosRegister.tenant_id == tenant_id)
                    .order_by(PosRegister.created_at.asc(), PosRegister.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def _get_register(
        session: AsyncSession, tenant_id: UUID, register_id: UUID
    ) -> PosRegister:
        register = (
            await session.execute(
                select(PosRegister).where(
                    PosRegister.tenant_id == tenant_id,
                    PosRegister.id == register_id,
                )
            )
        ).scalar_one_or_none()
        if register is None:
            raise NotFoundError(f"register {register_id} not found")
        return register

    # ----------------------------------------------------------- sessions ----

    @staticmethod
    async def open_session(
        session: AsyncSession,
        tenant_id: UUID,
        register_id: UUID,
        *,
        opening_float: object = "0.00",
        opened_by: UUID | None = None,
        profile_id: UUID | None = None,
        cashier_user_id: UUID | None = None,
        floats_by_method: dict[str, object] | None = None,
    ) -> PosSession:
        """OPEN the drawer. Two partial unique indexes back the two rules this
        pre-check exists to fail with a sentence for: one OPEN session per
        register, and — ERPNext's ``check_user_already_assigned`` — one OPEN
        session per cashier. Nobody holds two drawers.

        The profile is captured on the session at open time (defaulting to the
        register's own profile), so a later profile edit cannot retroactively
        change what this shift allowed. When a profile is in play, the opening
        user must be one of its grantees, and the float rows may only name
        methods the profile serves. ``floats_by_method`` opens the drawer PER
        METHOD (ERPNext's per-method opening entry); ``opening_float`` stays
        the cash leg — when the float names cash, it is mirrored there.
        """
        register = await PosService._get_register(session, tenant_id, register_id)
        if not register.is_active:
            raise ConflictError(f"register {register.code} is not active")
        resolved_cashier = cashier_user_id if cashier_user_id is not None else opened_by
        effective_profile_id = profile_id if profile_id is not None else register.profile_id
        profile = None
        if effective_profile_id is not None:
            profile = await PosProfileService.get(session, tenant_id, effective_profile_id)
            if resolved_cashier is not None and not await PosProfileService.can_operate(
                session, tenant_id, effective_profile_id, resolved_cashier
            ):
                raise ConflictError("this user does not operate this POS profile")
        if resolved_cashier is not None:
            held_elsewhere = (
                await session.execute(
                    select(PosSession.id).where(
                        PosSession.tenant_id == tenant_id,
                        PosSession.cashier_user_id == resolved_cashier,
                        PosSession.status == "OPEN",
                    )
                )
            ).scalar_one_or_none()
            if held_elsewhere is not None:
                raise ConflictError(
                    "this user already holds an open drawer; close it or hand it over first"
                )
        open_now = (
            await session.execute(
                select(PosSession.id).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.register_id == register_id,
                    PosSession.status == "OPEN",
                )
            )
        ).scalar_one_or_none()
        if open_now is not None:
            raise ConflictError(f"register {register.code} already has an open session")

        allowed_methods = (
            set(profile.allowed_payment_methods or []) if profile is not None else {"cash"}
        )
        floats: dict[str, Decimal] = {}
        if floats_by_method:
            unknown = set(map(str, floats_by_method)) - allowed_methods
            if unknown:
                raise ValidationError(
                    f"float methods {sorted(unknown)} are not enabled on this profile; "
                    f"allowed {sorted(allowed_methods)}"
                )
            floats = {
                str(method): _float_amount(amount, f"float[{method}]")
                for method, amount in floats_by_method.items()
            }
        elif "cash" in allowed_methods:
            floats = {"cash": to_money(opening_float, "opening_float")}
        cash_float = floats.get("cash", to_money(opening_float, "opening_float"))

        pos_session = PosSession(
            tenant_id=tenant_id,
            register_id=register_id,
            profile_id=effective_profile_id,
            cashier_user_id=resolved_cashier,
            opened_by_user_id=opened_by,
            opening_float=cash_float,
        )
        session.add(pos_session)
        await session.flush()
        for method, amount in floats.items():
            session.add(
                PosSessionFloat(
                    tenant_id=tenant_id,
                    session_id=pos_session.id,
                    method=method,
                    amount=amount,
                )
            )
        await session.flush()
        return pos_session

    @staticmethod
    async def _get_session(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> PosSession:
        pos_session = (
            await session.execute(
                select(PosSession).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.id == session_id,
                )
            )
        ).scalar_one_or_none()
        if pos_session is None:
            raise NotFoundError(f"pos session {session_id} not found")
        return pos_session

    @staticmethod
    def _ensure_holds_shift(
        pos_session: PosSession, actor_user_id: UUID | None, *, override: bool
    ) -> None:
        """The actor must hold this drawer, or hold ``pos:override`` (a manager covering for it).

        A drawer with no holder (legacy rows) stays open to everyone, as before. An UNKNOWN actor
        on a drawer that has a holder is refused: HTTP always supplies the user, so a missing one is
        an internal caller, and "unknown" must not be a way around the check.
        """
        holder = pos_session.cashier_user_id
        if holder is None or override or actor_user_id == holder:
            return
        raise PermissionDeniedError("this drawer is held by another cashier")

    @staticmethod
    def _enforce_discount_ceiling(
        profile: PosProfile | None,
        discount_total: object,
        subtotal: object,
        *,
        override: bool,
    ) -> None:
        """Refuse a discount above the till's ceiling unless the caller holds ``pos:override``.

        A till with no profile has no configured ceiling; it gets the safe default (0, so every
        discount needs the override) rather than a free pass, otherwise leaving the profile off
        would switch the control off.
        """
        if override:
            return
        if profile is None:
            if to_money(discount_total or "0", "discount_total") > 0:
                raise ValidationError(
                    "this till has no profile, so its discount ceiling is 0% and any discount "
                    "needs an approval"
                )
            return
        PosProfileService.ensure_discount_allowed(profile, discount_total, subtotal, approved=False)

    @staticmethod
    def _ensure_session_current(
        pos_session: PosSession, *, tz: str | None = None, now: datetime | None = None
    ) -> None:
        """A shift belongs to a day (ERPNext's ``Outdated POS Opening Entry``).

        A session opened yesterday and never closed may not keep selling: the
        close would reconcile two trading days into one report. "Yesterday" is
        the MERCHANT's day (``tenants.timezone``), never UTC's: a Cairo till
        opened at 23:30 must be stale at 00:30, not at 02:00. ``tz`` falls back
        through the same chain analytics uses (deployment zone, then UTC).
        """
        from app.modules.analytics.timekit import merchant_day

        opened = pos_session.opened_at
        if opened is None:
            return
        today = merchant_day(now or datetime.now(UTC), tz)
        if merchant_day(opened, tz) != today:
            raise ConflictError(
                "this session was opened on a previous day; close it and open a new one"
            )

    @staticmethod
    async def _shop_timezone(session: AsyncSession, tenant_id: UUID) -> str | None:
        """The zone this merchant counts its days in (``tenants.timezone``), or None."""
        from app.modules.identity.models import Tenant

        return (
            await session.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()

    @staticmethod
    async def get_session(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """The session plus its live cash position — what the closing screen shows."""
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        inflow, outflow = await PosService._cash_totals(session, tenant_id, pos_session.id)
        expected_now = Decimal(pos_session.opening_float) + inflow - outflow
        floats = (
            await session.execute(
                select(PosSessionFloat).where(
                    PosSessionFloat.tenant_id == tenant_id,
                    PosSessionFloat.session_id == pos_session.id,
                )
            )
        ).scalars().all()
        return {
            "session": pos_session,
            "inflow": inflow,
            "outflow": outflow,
            "expected_now": expected_now,
            "floats": list(floats),
        }

    # -------------------------------------------------------------- cash ----

    @staticmethod
    async def _cash_totals(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> tuple[Decimal, Decimal]:
        rows = (
            await session.execute(
                select(
                    PosCashMovement.direction,
                    func.coalesce(func.sum(PosCashMovement.amount), Decimal("0")),
                )
                .where(
                    PosCashMovement.tenant_id == tenant_id,
                    PosCashMovement.session_id == session_id,
                )
                .group_by(PosCashMovement.direction)
            )
        ).all()
        inflow = next((Decimal(a) for d, a in rows if d == "in"), Decimal("0"))
        outflow = next((Decimal(a) for d, a in rows if d == "out"), Decimal("0"))
        return inflow, outflow

    @staticmethod
    async def record_cash_movement(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        direction: str,
        reason: str,
        amount: object,
        created_by: UUID | None = None,
        shift_override: bool = False,
        ceiling_override: bool = False,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> PosCashMovement:
        """Book a manual cash event on an OPEN session.

        cash_sale/cash_refund are the sell flow's rows: writing one by hand
        would claim money the order ledger does not show (§189).
        """
        if direction not in _CASH_DIRECTIONS:
            raise ValidationError(f"direction must be one of {sorted(_CASH_DIRECTIONS)}")
        if reason not in _MANUAL_CASH_REASONS:
            if reason in _SALE_ONLY_CASH_REASONS:
                raise ValidationError(f"reason '{reason}' is written by the sell flow only")
            raise ValidationError(f"reason must be one of {sorted(_MANUAL_CASH_REASONS)}")
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        PosService._ensure_holds_shift(pos_session, created_by, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError("cash rows are booked on the open session only")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        cleaned_amount = _positive_amount(amount, "amount")
        if direction == "out" and reason in {"pay_out", "cash_drop"}:
            # Cash leaving the drawer by hand: the owner's limit on what a cashier may take alone.
            PosProfileService.ensure_within_money_ceiling(
                await PosService.resolve_profile(session, tenant_id, pos_session),
                cleaned_amount,
                kind="cash_out",
                approved=ceiling_override,
            )
        row = PosCashMovement(
            tenant_id=tenant_id,
            session_id=session_id,
            direction=direction,
            reason=reason,
            amount=cleaned_amount,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by_user_id=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def _append_sale_cash(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        reason: str,
        amount: Decimal,
        created_by: UUID | None,
        reference_id: UUID,
    ) -> PosCashMovement:
        row = PosCashMovement(
            tenant_id=tenant_id,
            session_id=session_id,
            direction="in" if reason == "cash_sale" else "out",
            reason=reason,
            amount=amount,
            reference_type="order",
            reference_id=reference_id,
            created_by_user_id=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    # --------------------------------------------------------------- scan ----

    @staticmethod
    async def resolve_profile(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> PosProfile | None:
        """The session's profile, or None for a profile-less (legacy) register."""
        if pos_session.profile_id is None:
            return None
        return await PosProfileService.get(session, tenant_id, pos_session.profile_id)

    @staticmethod
    async def scan(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        identifier_type: str,
        value: str,
    ) -> dict:
        """§179 THE scan entry point — an identifier resolves to one variant.

        Read-only: it resolves the variant, confirms the product is sellable and
        prices it off the tenant's ladder. An unknown code resolves to nothing
        (``found: False``) rather than a half-answer, so the till can beep
        without a 404.
        """
        from app.modules.catalog.service import CatalogService
        from app.modules.orders.service import sellable_refusal

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; open a new one to scan")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        register = await PosService._get_register(session, tenant_id, pos_session.register_id)

        variant = await CatalogService.resolve_identifier(
            session, tenant_id, identifier_type, value
        )
        if variant is None:
            return {"found": False}
        product = await CatalogService.get_product(session, tenant_id, variant.product_id)
        refusal = sellable_refusal(None if product is None else product.status)
        if refusal is not None:
            return {"found": False, "refusal": refusal}
        # ERPNext `POS Item Group`: a scoped terminal refuses what its profile
        # does not serve — the scan and the grid see the same catalog.
        scope = await PosService._item_group_scope(session, tenant_id, pos_session)
        if scope is not None and (
            product is None
            or product.category_id is None
            or str(product.category_id) not in scope
        ):
            return {"found": False, "refusal": "this product is outside this terminal's catalog"}

        from app.core.tenancy import resolve_tenant_currency

        currency = await resolve_tenant_currency(session, tenant_id)
        price = await CatalogService.price_for(
            session, tenant_id, variant, currency=currency, quantity=1
        )
        return {
            "found": True,
            "variant_id": variant.id,
            "product_id": variant.product_id,
            "title": variant.title or (product.title if product else ""),
            "sku": variant.sku,
            "unit_price": str(price),
            "warehouse_id": register.warehouse_id,
        }

    # ------------------------------------------------------------- browse ----

    @staticmethod
    async def _item_group_scope(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> set[str] | None:
        """The session profile's category ids, or None when unscoped."""
        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        ids = (profile.item_group_ids or []) if profile is not None else []
        return {str(i) for i in ids} or None

    @staticmethod
    async def _ensure_cart_in_scope(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        items: list[dict],
    ) -> None:
        """Refuse a cart line the till's profile does not serve (ERPNext `POS Item Group`).

        ``scan`` and ``browse`` already hide what a scoped terminal does not carry, but a client
        can name a variant id directly. Quote, sell and the new half of an exchange all take ids
        from the wire, so the same rule is applied to them here, in one read: a product with no
        category counts as outside any scope, exactly as in ``scan``.
        """
        scope = await PosService._item_group_scope(session, tenant_id, pos_session)
        if scope is None:
            return
        from app.modules.catalog.service import CatalogService

        wanted: set[UUID] = set()
        for item in items:
            try:
                wanted.add(UUID(str(item["variant_id"])))
            except (KeyError, ValueError):
                continue  # the pricing step reports a malformed id with the proper message
        if not wanted:
            return
        variants = await CatalogService.get_variants_by_ids(session, tenant_id, wanted)
        products = await CatalogService.get_products_by_ids(
            session, tenant_id, sorted({v.product_id for v in variants.values()})
        )
        outside = sorted(
            str(variant.id)
            for variant in variants.values()
            if (product := products.get(variant.product_id)) is None
            or product.category_id is None
            or str(product.category_id) not in scope
        )
        if outside:
            raise ValidationError(
                "this product is outside this terminal's catalog: " + ", ".join(outside)
            )

    @staticmethod
    async def browse(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """The till's catalog grid beside the scanner (§plan phase 3).

        One parameter-bound read model (§137): active variants of active
        products joined to the register's warehouse bins, priced through the
        catalog's own tier rules. The grid never writes — every mutation still
        goes through ``sell``.
        """
        from app.modules.catalog.models import Product, ProductVariant
        from app.modules.inventory.models import InventoryBalance

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; open a new one to browse")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        register = await PosService._get_register(session, tenant_id, pos_session.register_id)
        if limit < 1 or limit > 60:
            raise ValidationError("limit must be between 1 and 60")
        if offset < 0:
            raise ValidationError("offset must not be negative")

        conditions = [
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.is_active.is_(True),
            Product.tenant_id == tenant_id,
            # The same sellability rule the scan and checkout enforce.
            Product.status == "active",
        ]
        scope = await PosService._item_group_scope(session, tenant_id, pos_session)
        if scope is not None:
            # in_ excludes NULL categories — a scoped terminal serves only what
            # its profile named, never the uncategorised rest.
            conditions.append(Product.category_id.in_([UUID(s) for s in scope]))
        needle = (q or "").strip()
        if needle:
            from app.core.sql import LIKE_ESCAPE, like_pattern

            like = like_pattern(needle)
            conditions.append(
                or_(
                    ProductVariant.title.ilike(like, escape=LIKE_ESCAPE),
                    ProductVariant.sku.ilike(like, escape=LIKE_ESCAPE),
                    Product.title.ilike(like, escape=LIKE_ESCAPE),
                )
            )

        total = (
            await session.execute(
                select(func.count())
                .select_from(ProductVariant)
                .join(Product, Product.id == ProductVariant.product_id)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(ProductVariant, Product.title.label("product_title"))
                .join(Product, Product.id == ProductVariant.product_id)
                .where(*conditions)
                .order_by(ProductVariant.created_at.asc(), ProductVariant.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        variant_ids = [variant.id for variant, _title in rows]

        # Prices come from the catalog's own ladder rules — the grid can never
        # disagree with what ``sell`` will charge.
        from app.core.tenancy import resolve_tenant_currency
        from app.modules.catalog.service import CatalogService

        currency = await resolve_tenant_currency(session, tenant_id)
        ladders = await CatalogService.price_tiers_for_many(
            session, tenant_id, variant_ids, currency=currency
        )

        stocks: dict[UUID, int] = {}
        if variant_ids:
            for variant_id, on_hand, reserved in (
                await session.execute(
                    select(
                        InventoryBalance.variant_id,
                        InventoryBalance.on_hand,
                        InventoryBalance.reserved,
                    ).where(
                        InventoryBalance.tenant_id == tenant_id,
                        InventoryBalance.warehouse_id == register.warehouse_id,
                        InventoryBalance.variant_id.in_(variant_ids),
                    )
                )
            ).all():
                stocks[variant_id] = int(on_hand) - int(reserved)

        items = []
        for variant, product_title in rows:
            unit_price = CatalogService.tiered_unit_price(
                variant.price, ladders.get(variant.id, []), 1
            )
            items.append(
                {
                    "variant_id": str(variant.id),
                    "product_id": str(variant.product_id),
                    "title": variant.title or product_title or "",
                    "sku": variant.sku,
                    "unit_price": str(to_money(unit_price, "unit_price")),
                    "available": stocks.get(variant.id, 0),
                }
            )
        return {"items": items, "total": int(total), "limit": limit, "offset": offset}

    # -------------------------------------------------------------- quote ----

    @staticmethod
    async def quote(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        items: list[dict],
        discount_total: object = None,
    ) -> dict:
        """Price a cart WITHOUT writing anything — what the till shows the customer.

        The same ``compute_totals`` the order will use, so the number on screen
        is the number charged. Line discounts (§189: the cashier types a
        percentage on a piece) compose with the caller's invoice-level
        discount into one discount_total — no approval gate: a ground-shop
        discount is the cashier's call.
        """

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; open a new one to quote")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        if not items:
            raise ValidationError("a quote must contain at least one item")

        await PosService._ensure_cart_in_scope(session, tenant_id, pos_session, items)
        subtotal, _lines, line_discounts = await PosService._price_lines(
            session, tenant_id, items
        )
        composed = (
            None
            if discount_total is None and line_discounts == 0
            else to_money(
                to_money(discount_total or 0, "discount_total") + line_discounts,
                "discount_total",
            )
        )
        try:
            totals = compute_totals(subtotal=subtotal, discount=composed)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        return {
            "subtotal": str(totals["subtotal"]),
            "discount_total": str(totals["discount_total"]),
            "grand_total": str(totals["grand_total"]),
        }

    @staticmethod
    def _line_discount_pct(item: dict) -> Decimal:
        """The item's optional per-line discount, percent in [0, 100]."""
        raw = item.get("discount_pct")
        if raw is None:
            return Decimal("0.00")
        try:
            pct = to_money(raw, "discount_pct")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if pct < 0 or pct > 100:
            raise ValidationError("discount_pct must be between 0 and 100")
        return pct

    @staticmethod
    async def _price_lines(
        session: AsyncSession, tenant_id: UUID, items: list[dict]
    ) -> tuple[Decimal, list[tuple[UUID, int, Decimal, Decimal]], Decimal]:
        """Batch-price a cart identically to ``create_order`` (§179/§180).

        Returns the GROSS subtotal, the (variant_id, quantity, unit_price,
        discount_pct) tuples, and the lines' total discount — the same
        per-quantity tier ladder and the same discount math the order will
        read, so a quote and the order it precedes can never disagree.
        """
        from app.modules.catalog.service import CatalogService

        line_ids: list[UUID | None] = []
        parse_errors: list[Exception | None] = []
        for item in items:
            try:
                line_ids.append(UUID(str(item["variant_id"])))
                parse_errors.append(None)
            except (KeyError, ValueError) as exc:
                line_ids.append(None)
                parse_errors.append(exc)

        fetch_ids = sorted({vid for vid in line_ids if vid is not None})
        variants = await CatalogService.get_variants_by_ids(session, tenant_id, fetch_ids)
        from app.core.tenancy import resolve_tenant_currency

        currency = await resolve_tenant_currency(session, tenant_id)
        ladders = await CatalogService.price_tiers_for_many(
            session, tenant_id, fetch_ids, currency=currency
        )

        prepared: list[tuple[UUID, int, Decimal, Decimal]] = []
        for item, variant_id, parse_error in zip(items, line_ids, parse_errors, strict=True):
            if parse_error is not None:
                raise ValidationError("each item needs a valid variant_id")
            variant = variants.get(variant_id) if variant_id is not None else None
            if variant is None or not variant.is_active:
                raise NotFoundError(f"variant {variant_id} not found")
            quantity = PosService._positive_qty(item.get("quantity"))
            unit_price = CatalogService.tiered_unit_price(
                variant.price, ladders.get(variant.id, []), quantity
            )
            prepared.append(
                (
                    variant.id,
                    quantity,
                    to_money(unit_price, "unit_price"),
                    PosService._line_discount_pct(item),
                )
            )

        subtotal = to_money(
            sum(
                (price * quantity for _v, quantity, price, _pct in prepared),
                Decimal("0"),
            ),
            "subtotal",
        )
        line_discounts = to_money(
            sum(
                (
                    price * quantity * pct / Decimal("100")
                    for _v, quantity, price, pct in prepared
                    if pct
                ),
                Decimal("0"),
            ),
            "line discounts",
        )
        return subtotal, prepared, line_discounts

    @staticmethod
    def _positive_qty(value: object) -> int:
        try:
            quantity = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValidationError("quantity must be a positive integer") from None
        if quantity <= 0:
            raise ValidationError("quantity must be greater than zero")
        return quantity

    # --------------------------------------------------------------- sell ----

    @staticmethod
    async def sell(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        customer_id: UUID | None = None,
        items: list[dict] | None = None,
        tenders: list[dict] | None = None,
        method: str | None = None,
        amount: object | None = None,
        discount_total: object = None,
        tendered_cash: object | None = None,
        held_cart_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
        discount_override: bool = False,
    ) -> dict:
        """One POS sale = one commerce command chain (§189).

        CreateOrder (channel="pos", register's warehouse, optional discount) →
        capture each tender → the §140 reservation machinery settles the stock.
        The drawer's cash row is written here, in the same transaction, because
        the money is in the drawer now.

        Two tender shapes, never both: a single ``method``/``amount`` (the
        original call, kept for compatibility) or a ``tenders`` list
        ([{method, amount}]) for a split payment. ``tendered_cash`` is what the
        customer handed over for a cash sale, so the change can be computed and
        printed. ``held_cart_id`` resumes a parked cart atomically: its stored
        lines, customer and discount become this sale, and the cart is claimed
        inside the same transaction.
        """
        from app.modules.orders.service import OrderService

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; open a new one to sell")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        if held_cart_id is not None:
            # The cart's lines BECOME this sale; its customer and discount fill
            # in when the caller did not name their own. A cart that is already
            # gone reports the CONFLICT (someone resumed it), not a bare 404 —
            # same sentence the claim below uses.
            try:
                held = await PosService.get_held_cart(session, tenant_id, held_cart_id)
            except NotFoundError:
                raise ConflictError(
                    "this held cart was already resumed or released"
                ) from None
            if held.session_id != pos_session.id:
                raise ConflictError("this held cart belongs to a different session")
            items = list(held.items or [])
            if customer_id is None and held.customer_id is not None:
                customer_id = held.customer_id
            if discount_total is None and held.discount_total is not None:
                discount_total = held.discount_total
        if not items:
            raise ValidationError("a sale must contain at least one item")
        # Same rule /quote applies. Without it a zero/negative quantity reached
        # OrderService, which raises a bare ValueError -> HTTP 500 (retryable).
        for item in items:
            PosService._positive_qty(item.get("quantity"))
        register = await PosService._get_register(session, tenant_id, pos_session.register_id)
        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        if profile is not None and not profile.is_active:
            raise ConflictError("this POS profile is not active")
        await PosService._ensure_cart_in_scope(session, tenant_id, pos_session, items)

        # A sale that names no tender charges the profile's preselected method
        # (ERPNext `set_grand_total_to_default_mop`); cash stays the fallback.
        default_method = (profile.default_payment_method if profile is not None else None) or "cash"
        tender_lines = PosService._normalise_tenders(
            tenders, method, amount, default_method=default_method
        )
        if profile is not None:
            PosService._ensure_methods_allowed(profile, tender_lines)

        # Walk-in: fall back to the profile's default customer when none was
        # given and the profile does not require one.
        resolved_customer_id = await PosService._resolve_customer(
            session, tenant_id, profile, customer_id
        )

        if held_cart_id is not None:
            # Claim the cart inside THIS transaction: DELETE .. RETURNING takes
            # the row lock, so a concurrent resume of the same cart blocks and
            # then sees zero rows. A failed sell rolls the claim back with the
            # rest of the transaction — the basket never dies to a refusal.
            claimed = (
                await session.execute(
                    delete(PosHeldCart)
                    .where(PosHeldCart.tenant_id == tenant_id, PosHeldCart.id == held_cart_id)
                    .returning(PosHeldCart.id)
                )
            ).scalar_one_or_none()
            if claimed is None:
                raise ConflictError("this held cart was already resumed or released")

        order = await OrderService.create_order(
            session,
            tenant_id,
            resolved_customer_id,
            items,
            channel="pos",
            warehouse_id=register.warehouse_id,
            discount_total=discount_total,
        )
        # The ceiling is checked on what was actually PRICED onto the order (document discount plus
        # every line discount), not on what the caller asked for, so a discount cannot be dodged
        # by moving it between the two. A refusal rolls the sale back: no order, no stock.
        PosService._enforce_discount_ceiling(
            profile, order.discount_total, order.subtotal, override=discount_override
        )

        # Capture the tenders. A tender with no explicit amount settles the
        # whole order — the exact behaviour of the old single-payment route,
        # where ``amount`` defaulted to ``order.grand_total``.
        resolved_tenders = [
            {
                "method": t["method"],
                "amount": t["amount"] if t["amount"] is not None else order.grand_total,
            }
            for t in tender_lines
        ]
        # ERPNext `validate_pos`: the tenders must settle the whole order. A
        # cash over-tender is expressed through ``tendered_cash`` (the change
        # is computed from it), never by inflating a tender line — a card
        # tender above the total would silently overpay the order, and a short
        # tender would print a receipt for an order it did not settle.
        if all(t["amount"] is not None for t in tender_lines):
            tendered_total = to_money(
                sum((t["amount"] for t in tender_lines), Decimal("0")), "tenders"
            )
            grand = to_money(order.grand_total, "grand_total")
            if tendered_total != grand:
                raise ValidationError(
                    f"tenders total {tendered_total} but the order is {grand}"
                )
        for tender in resolved_tenders:
            await OrderService.add_payment(
                session,
                tenant_id,
                order.id,
                method=tender["method"],
                amount=tender["amount"],
            )

        # Cash into the drawer: one aggregate row for however many cash tenders
        # were taken (a split with two cash legs is still one physical deposit).
        cash_total = sum(
            (t["amount"] for t in resolved_tenders if t["method"] == "cash"), Decimal("0")
        )
        if cash_total > 0:
            await PosService._append_sale_cash(
                session,
                tenant_id,
                pos_session.id,
                reason="cash_sale",
                amount=to_money(cash_total, "cash_total"),
                created_by=actor_user_id,
                reference_id=order.id,
            )

        tendered, change = PosService._settle_change(cash_total, tendered_cash)

        receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            tendered_amount=tendered if cash_total > 0 else None,
            change_amount=change if cash_total > 0 else None,
        )
        return {
            "order_id": order.id,
            "order_number": order.number,
            "receipt_id": receipt.id,
            "receipt_number": receipt.number,
            "grand_total": str(order.grand_total),
            "payment_count": len(tender_lines),
        }

    @staticmethod
    def _settle_change(
        cash_due: Decimal, tendered_cash: object | None
    ) -> tuple[Decimal | None, Decimal | None]:
        """Tender vs owed → (tendered, change), both None when no cash moved.

        ``cash_due`` is the cash portion of the order (what the customer OWES in
        cash). ``tendered_cash`` is what they actually handed over. The change is
        the difference, and it may never be negative — a customer who handed
        over less than they owe is a refused sale, not a negative change.

        When no cash tender was named, nothing was handed-over-and-returned, so
        the pair stays None; a card sale has no change by construction.
        """
        if cash_due <= 0:
            return None, None
        tendered = (
            to_money(tendered_cash, "tendered_cash")
            if tendered_cash is not None
            else cash_due
        )
        if tendered < cash_due:
            raise ConflictError(
                f"cash tendered {tendered} is less than the cash due {cash_due}"
            )
        return tendered, tendered - cash_due

    @staticmethod
    def _normalise_tenders(
        tenders: list[dict] | None,
        method: str | None,
        amount: object | None,
        *,
        default_method: str = "cash",
    ) -> list[dict]:
        """Resolve the two tender shapes into one [{method, amount}] list.

        An explicitly EMPTY tenders list is refused, not treated as "nothing
        named": a caller bug would otherwise silently charge the profile's
        default method with the whole total.
        """
        if tenders is not None and not tenders:
            raise ValidationError("a sale must contain at least one tender")
        if tenders:
            if method is not None or amount is not None:
                raise ValidationError("pass either tenders or method/amount, not both")
            lines: list[dict] = []
            for tender in tenders:
                try:
                    one_method = str(tender["method"])
                    one_amount = _positive_amount(tender["amount"], "tender amount")
                except (KeyError, TypeError):
                    raise ValidationError("each tender needs a method and an amount") from None
                if one_method not in _SALE_METHODS:
                    raise ValidationError(f"method must be one of {sorted(_SALE_METHODS)}")
                lines.append({"method": one_method, "amount": one_amount})
            if not lines:
                raise ValidationError("a sale must contain at least one tender")
            return lines
        # Legacy single-tender shape.
        chosen = method or default_method
        if chosen not in _SALE_METHODS:
            raise ValidationError(f"method must be one of {sorted(_SALE_METHODS)}, got {chosen!r}")
        resolved = None if amount is None else _positive_amount(amount, "amount")
        return [{"method": chosen, "amount": resolved}]

    @staticmethod
    def _ensure_methods_allowed(profile: PosProfile, tenders: list[dict]) -> None:
        allowed = set(profile.allowed_payment_methods or [])
        refused = {t["method"] for t in tenders if t["method"] not in allowed}
        if refused:
            raise ValidationError(
                f"payment methods {sorted(refused)} are not enabled on this profile; "
                f"allowed {sorted(allowed)}"
            )

    @staticmethod
    async def _resolve_customer(
        session: AsyncSession,
        tenant_id: UUID,
        profile: PosProfile | None,
        customer_id: UUID | None,
    ) -> UUID:
        if customer_id is not None:
            return customer_id
        # The till says every sale needs a named customer: a walk-in is not one. Without this the
        # flag was stored and shown but never enforced, and a sale with no customer went through.
        if profile is not None and profile.require_customer:
            raise ValidationError("this till requires a customer on every sale")
        if profile is not None and profile.default_customer_id is not None:
            return profile.default_customer_id
        # No profile (or one without a walk-in): a ground-shop till still
        # needs somewhere to book the sale — the tenant's shared walk-in
        # customer, bootstrapped once and reused (the get_default_warehouse
        # pattern). Profile-scoped tills keep their own default.
        from app.modules.customers.models import Customer
        from app.modules.customers.service import CustomerService

        walk_in = (
            await session.execute(
                select(Customer.id)
                .where(
                    Customer.tenant_id == tenant_id,
                    Customer.name == "زبون نقدي",
                    Customer.is_blocked.is_(False),
                )
                .order_by(Customer.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if walk_in is not None:
            return walk_in
        created = await CustomerService.create_from_import(
            session, tenant_id, name="زبون نقدي", source="pos"
        )
        return created.id

    @staticmethod
    async def _issue_receipt(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        order,
        *,
        tendered_amount: Decimal | None = None,
        change_amount: Decimal | None = None,
        number_prefix: str = "POS",
        kind: str = "sale",
        exchange_return_receipt_id: UUID | None = None,
    ) -> PosReceipt:
        last_exc: IntegrityError | None = None
        for _attempt in range(_NUMBER_ATTEMPTS):
            number = f"{number_prefix}-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            receipt = PosReceipt(
                tenant_id=tenant_id,
                order_id=order.id,
                session_id=pos_session.id,
                number=number,
                kind=kind,
                tendered_amount=tendered_amount,
                change_amount=change_amount,
                exchange_return_receipt_id=exchange_return_receipt_id,
            )
            try:
                async with session.begin_nested():
                    session.add(receipt)
                    await session.flush()
                return receipt
            except IntegrityError as exc:
                last_exc = exc
        raise ConflictError("could not allocate a receipt number") from last_exc

    # -------------------------------------------------------------- close ----

    @staticmethod
    async def close_session(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        counted_cash: object,
        counted_by_method: dict | None = None,
        closed_by: UUID | None = None,
        shift_override: bool = False,
    ) -> PosSession:
        """OPEN → CLOSED; the POS cash reconciliation (§188) happens here.

        expected = opening float + cash in − cash out, computed from the rows.
        The variance is stored, never applied to anything — the merchant
        decides what a short drawer means.

        When ``counted_by_method`` is supplied, one reconciliation row per
        method is written (expected from the session's payments vs the counted
        figure), so a merchant taking card and wallet sees the truth about each
        instead of a single cash pair (§188).
        """
        from app.core.events.writer import add_outbox_event

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        PosService._ensure_holds_shift(pos_session, closed_by, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError(f"pos session is already {pos_session.status}")
        counted = to_money(counted_cash, "counted_cash")
        if counted < 0:
            raise ValidationError("counted_cash must not be negative")
        inflow, outflow = await PosService._cash_totals(session, tenant_id, pos_session.id)
        expected = Decimal(pos_session.opening_float) + inflow - outflow
        variance = counted - expected

        # Per-method reconciliation, written BEFORE the status flips so the rows
        # belong to the same transaction as the close.
        # ``counted_cash`` is the closer's cash count. When no per-method figure for cash
        # came with it, it still IS the cash figure: without this a short drawer was
        # recorded as "matched" in the reconciliation and the shift report.
        counted_for_rows = dict(counted_by_method or {})
        counted_for_rows.setdefault("cash", counted)
        recon_rows = await PosService._write_reconciliation(
            session, tenant_id, pos_session, counted_for_rows
        )

        pos_session.status = "CLOSED"
        pos_session.counted_cash = counted
        pos_session.expected_cash = expected
        pos_session.variance = variance
        pos_session.closed_by_user_id = closed_by
        pos_session.closed_at = datetime.now(UTC)
        await session.flush()

        # The close is a business event: analytics reconciles cash from the
        # rows, never by querying this session's columns mid-transaction (§190).
        from app.modules.orders.models import Order

        sales_row = (
            await session.execute(
                select(
                    func.count(PosReceipt.id),
                    func.coalesce(func.sum(Order.grand_total), 0),
                    func.coalesce(func.sum(Order.tax_total), 0),
                )
                .select_from(PosReceipt)
                .join(Order, Order.id == PosReceipt.order_id)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.session_id == pos_session.id,
                    PosReceipt.kind == "sale",
                )
            )
        ).one()
        returns_row = (
            await session.execute(
                select(
                    func.count(func.distinct(PosReturnLine.receipt_id)),
                    func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                )
                .select_from(PosReturnLine)
                .join(PosReceipt, PosReceipt.id == PosReturnLine.receipt_id)
                .where(
                    PosReturnLine.tenant_id == tenant_id,
                    PosReceipt.session_id == pos_session.id,
                )
            )
        ).one()
        await add_outbox_event(
            session,
            aggregate_type="pos_session",
            aggregate_id=pos_session.id,
            event_type="pos.session.closed",
            tenant_id=tenant_id,
            payload={
                "pos.session.closed": True,
                "session_id": str(pos_session.id),
                "register_id": str(pos_session.register_id),
                "expected": str(expected),
                "counted": str(counted),
                "variance": str(variance),
                "by_method": [
                    {
                        "method": r.method,
                        "expected": str(r.expected_amount),
                        "counted": str(r.counted_amount),
                        "variance": str(r.variance),
                    }
                    for r in recon_rows
                ],
                # Projection seed figures — the worker RECOMPUTES these from
                # the ledgers (idempotent), the payload rides for consumers
                # that never touch the database.
                "business_date": (
                    pos_session.closed_at.date().isoformat()
                    if pos_session.closed_at
                    else None
                ),
                "invoice_count": int(sales_row[0]),
                "sales_total": str(to_money(sales_row[1], "sales_total")),
                "taxes_total": str(to_money(sales_row[2], "taxes_total")),
                "returns_count": int(returns_row[0]),
                "returns_total": str(to_money(returns_row[1], "returns_total")),
            },
            producer="pos",
        )
        return pos_session

    @staticmethod
    async def _expected_by_method(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> dict[str, Decimal]:
        """What each payment method SHOULD hold, per the ledgers (§188).

        Cash speaks the drawer's arithmetic: float + cash in − cash out (the
        cash rows are net — change never leaves a second hole). Every other
        method is its captured payments minus the refunds placed against them,
        so a refunded card sale no longer makes the close report lie. Cash is
        always present: the drawer holds its float even on a card-only shift.
        """
        from app.modules.orders.models import OrderPayment, Refund

        # Semi-join, never a row-multiplying join: an order carries BOTH its
        # sale and its return receipt, and joining payments on receipts would
        # count every payment once per receipt. The session's orders come from
        # an IN-subquery, so each payment is summed exactly once.
        session_orders = (
            select(PosReceipt.order_id).where(
                PosReceipt.tenant_id == tenant_id,
                PosReceipt.session_id == pos_session.id,
            )
        )
        payment_totals = dict(
            (
                await session.execute(
                    select(
                        OrderPayment.method,
                        func.coalesce(func.sum(OrderPayment.amount), 0),
                    )
                    .where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id.in_(session_orders),
                    )
                    .group_by(OrderPayment.method)
                )
            ).all()
        )
        refund_totals = dict(
            (
                await session.execute(
                    select(
                        OrderPayment.method,
                        func.coalesce(func.sum(Refund.amount), 0),
                    )
                    .select_from(Refund)
                    .join(OrderPayment, Refund.payment_id == OrderPayment.id)
                    .where(
                        Refund.tenant_id == tenant_id,
                        Refund.status != "rejected",
                        OrderPayment.order_id.in_(session_orders),
                    )
                    .group_by(OrderPayment.method)
                )
            ).all()
        )
        inflow, outflow = await PosService._cash_totals(session, tenant_id, pos_session.id)
        expected: dict[str, Decimal] = {
            "cash": Decimal(pos_session.opening_float) + inflow - outflow
        }
        for method in set(payment_totals) | set(refund_totals):
            if method == "cash":
                continue
            expected[method] = to_money(
                payment_totals.get(method, 0), "expected"
            ) - to_money(refund_totals.get(method, 0), "refunded")
        return expected

    @staticmethod
    async def _write_reconciliation(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        counted_by_method: dict,
    ) -> list[PosSessionReconciliation]:
        """One reconciliation row per method the session actually saw.

        Expected comes from the ledgers (``_expected_by_method``); counted
        comes from the closer. A method the closer counted but the session
        never took is still recorded (expected 0) — an unexplained surplus is
        a finding, never a silent correction (§188).
        """
        expected_by_method = await PosService._expected_by_method(
            session, tenant_id, pos_session
        )
        methods = set(expected_by_method) | set(counted_by_method)
        rows: list[PosSessionReconciliation] = []
        for method in sorted(methods):
            expected_method = to_money(expected_by_method.get(method, 0), "expected")
            counted_raw = counted_by_method.get(method)
            counted_method = (
                to_money(counted_raw, "counted") if counted_raw is not None else expected_method
            )
            row = PosSessionReconciliation(
                tenant_id=tenant_id,
                session_id=pos_session.id,
                method=method,
                expected_amount=expected_method,
                counted_amount=counted_method,
                variance=counted_method - expected_method,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        return rows

    @staticmethod
    async def list_reconciliation(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> list[PosSessionReconciliation]:
        rows = (
            (
                await session.execute(
                    select(PosSessionReconciliation)
                    .where(
                        PosSessionReconciliation.tenant_id == tenant_id,
                        PosSessionReconciliation.session_id == session_id,
                    )
                    .order_by(PosSessionReconciliation.method.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    # ------------------------------------------------------- close preview ----

    @staticmethod
    async def close_preview(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """What the close screen counts against — ERPNext's ``get_invoices``.

        Per-method expected figures, the session's sales summary, and the live
        drawer arithmetic — all read-only, so the cashier sees the target
        before typing a single counted number.
        """
        from app.modules.orders.models import Order

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        expected = await PosService._expected_by_method(session, tenant_id, pos_session)
        # Sales figures count SALE receipts only — a return receipt points at
        # the same order and would double-count its total.
        sales = (
            await session.execute(
                select(
                    func.count(PosReceipt.id),
                    func.coalesce(func.sum(Order.grand_total), 0),
                    func.coalesce(func.sum(Order.tax_total), 0),
                )
                .select_from(PosReceipt)
                .join(Order, Order.id == PosReceipt.order_id)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.session_id == pos_session.id,
                    PosReceipt.kind == "sale",
                )
            )
        ).one()
        inflow, outflow = await PosService._cash_totals(session, tenant_id, pos_session.id)
        return {
            "session_id": pos_session.id,
            "status": pos_session.status,
            "by_method": [
                {"method": method, "expected": str(expected[method])}
                for method in sorted(expected)
            ],
            "invoice_count": int(sales[0]),
            "sales_total": str(to_money(sales[1], "sales_total")),
            "taxes_total": str(to_money(sales[2], "taxes_total")),
            "opening_float": str(pos_session.opening_float),
            "cash_in": str(inflow),
            "cash_out": str(outflow),
        }

    # ------------------------------------------------------------- lookup ----

    @staticmethod
    async def list_sessions(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        register_id: UUID | None = None,
    ) -> list[PosSession]:
        """Resume the till: the sessions behind this drawer, newest first."""
        query = select(PosSession).where(PosSession.tenant_id == tenant_id)
        if status is not None:
            if status not in ("OPEN", "CLOSED"):
                raise ValidationError("status must be OPEN or CLOSED")
            query = query.where(PosSession.status == status)
        if register_id is not None:
            query = query.where(PosSession.register_id == register_id)
        rows = (
            (
                await session.execute(
                    query.order_by(PosSession.opened_at.desc(), PosSession.id.desc()).limit(50)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def get_receipt(session: AsyncSession, tenant_id: UUID, receipt_id: UUID) -> dict:
        """The printed artifact: receipt header + order lines + tenders.

        Read-only and assembled from the owning modules' tables through this
        one parameter-bound read model (§137) — the till never writes them.
        """
        from app.modules.orders.models import Order, OrderItem, OrderPayment

        receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id, PosReceipt.id == receipt_id
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError(f"pos receipt {receipt_id} not found")
        order = (
            await session.execute(
                select(Order).where(Order.tenant_id == tenant_id, Order.id == receipt.order_id)
            )
        ).scalar_one_or_none()
        lines = (
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == receipt.order_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        tenders = (
            (
                await session.execute(
                    select(OrderPayment).where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id == receipt.order_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Return state of the ORDER, derived from the return lines — the
        # derived equivalent of ERPNext's "Credit Note Issued" marker.
        returned_by_variant: dict[UUID, int] = dict(
            (
                await session.execute(
                    select(
                        PosReturnLine.variant_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                    )
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReturnLine.order_id == receipt.order_id,
                    )
                    .group_by(PosReturnLine.variant_id)
                )
            ).all()
        )
        if receipt.kind == "return":
            # A return receipt shows what THIS return gave back, priced at the
            # original sale's lines.
            return_rows = (
                (
                    await session.execute(
                        select(PosReturnLine).where(
                            PosReturnLine.tenant_id == tenant_id,
                            PosReturnLine.receipt_id == receipt.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            item_by_variant = {item.variant_id: item for item in lines}
            lines_payload = [
                {
                    "variant_id": row.variant_id,
                    "title": (
                        item_by_variant[row.variant_id].title
                        if row.variant_id in item_by_variant
                        else None
                    ),
                    "sku": (
                        item_by_variant[row.variant_id].sku
                        if row.variant_id in item_by_variant
                        else None
                    ),
                    "quantity": row.quantity,
                    "unit_price": str(row.unit_price),
                    "total": str(row.refund_total),
                    "returned_qty": row.quantity,
                }
                for row in return_rows
            ]
        else:
            lines_payload = [
                {
                    "variant_id": line.variant_id,
                    "title": line.title,
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price": str(line.unit_price),
                    "total": str(line.total),
                    "returned_qty": int(returned_by_variant.get(line.variant_id, 0)),
                }
                for line in lines
            ]
        fully_returned = bool(lines) and all(
            int(returned_by_variant.get(item.variant_id, 0)) >= item.quantity
            for item in lines
        )
        return {
            "receipt": {
                "id": receipt.id,
                "number": receipt.number,
                "kind": receipt.kind,
                "exchange_return_receipt_id": receipt.exchange_return_receipt_id,
                "issued_at": receipt.issued_at.isoformat(),
                "tendered_amount": (
                    str(receipt.tendered_amount)
                    if receipt.tendered_amount is not None
                    else None
                ),
                "change_amount": (
                    str(receipt.change_amount) if receipt.change_amount is not None else None
                ),
            },
            "order": {
                "id": order.id if order else receipt.order_id,
                "number": order.number if order else None,
                "grand_total": str(order.grand_total) if order else None,
                "discount_total": str(order.discount_total) if order else None,
                "currency": order.currency if order else None,
                "fully_returned": fully_returned if receipt.kind == "sale" else None,
            },
            "lines": lines_payload,
            "tenders": [
                {"method": t.method, "amount": str(t.amount), "status": t.status}
                for t in tenders
            ],
        }

    @staticmethod
    async def list_receipts(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> list[dict]:
        """The shift's receipts with their return state — the refund picker.

        ``returned_units``/``refunded_total`` come from the return lines of
        the order (our derived equivalent of ERPNext's "Credit Note Issued"
        marker): a sale whose units all came back shows as fully returned
        without anyone flipping a status column.
        """
        rows = (
            (
                await session.execute(
                    select(PosReceipt)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id == session_id,
                    )
                    .order_by(PosReceipt.issued_at.desc(), PosReceipt.id.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return await PosService._receipt_rows(session, tenant_id, list(rows))

    @staticmethod
    async def search_receipts(
        session: AsyncSession, tenant_id: UUID, *, q: str, limit: int = 20
    ) -> list[dict]:
        """Find an original SALE receipt across every shift, by number — the refund picker's search.

        A return does not have to happen on the shift that made the sale, so the picker cannot be
        limited to the open drawer. The return state (``returned_units`` / ``refunded_total``) is
        read from the order's whole return history, never from one shift, so the quantity still
        returnable is right whichever drawer took the earlier returns. The refund itself is still
        settled on the CURRENT shift by ``return_sale``.
        """
        term = (q or "").strip()
        if len(term) < 3:
            raise ValidationError("search needs at least 3 characters")
        if limit < 1 or limit > 50:
            raise ValidationError("limit must be between 1 and 50")
        from app.core.sql import LIKE_ESCAPE, like_pattern

        rows = (
            (
                await session.execute(
                    select(PosReceipt)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.kind == "sale",
                        PosReceipt.number.ilike(like_pattern(term), escape=LIKE_ESCAPE),
                    )
                    .order_by(PosReceipt.issued_at.desc(), PosReceipt.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return await PosService._receipt_rows(session, tenant_id, list(rows))

    @staticmethod
    async def _receipt_rows(
        session: AsyncSession, tenant_id: UUID, rows: list[PosReceipt]
    ) -> list[dict]:
        """Receipts as picker rows, with return state from the order's whole return history."""
        order_ids = [r.order_id for r in rows]
        returned: dict[UUID, tuple[int, Decimal]] = {}
        if order_ids:
            for order_id, qty, total in (
                await session.execute(
                    select(
                        PosReturnLine.order_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                        func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                    )
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReturnLine.order_id.in_(order_ids),
                    )
                    .group_by(PosReturnLine.order_id)
                )
            ).all():
                returned[order_id] = (int(qty), to_money(total, "refunded"))
        out: list[dict] = []
        for r in rows:
            units, refunded = returned.get(r.order_id, (0, Decimal("0")))
            out.append(
                {
                    "id": r.id,
                    "number": r.number,
                    "kind": r.kind,
                    "exchange_return_receipt_id": r.exchange_return_receipt_id,
                    "order_id": r.order_id,
                    "session_id": r.session_id,
                    "issued_at": r.issued_at.isoformat(),
                    "tendered_amount": (
                        str(r.tendered_amount) if r.tendered_amount is not None else None
                    ),
                    "change_amount": (
                        str(r.change_amount) if r.change_amount is not None else None
                    ),
                    "returned_units": units if r.kind == "sale" else 0,
                    "refunded_total": str(refunded) if r.kind == "sale" else None,
                }
            )
        return out

    @staticmethod
    async def session_report(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """The shift's report — per method, cash trail, sales, returns, handovers.

        An OPEN session reports live figures; a CLOSED one replays the stored
        reconciliation rows. Either way it is arithmetic over rows — expected
        is computed, never remembered (§188).
        """
        from app.modules.orders.models import Order

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status == "CLOSED":
            recon = await PosService.list_reconciliation(session, tenant_id, session_id)
            by_method = [
                {
                    "method": r.method,
                    "expected": str(r.expected_amount),
                    "counted": str(r.counted_amount),
                    "variance": str(r.variance),
                }
                for r in recon
            ]
        else:
            expected = await PosService._expected_by_method(session, tenant_id, pos_session)
            by_method = [
                {"method": m, "expected": str(expected[m]), "counted": None, "variance": None}
                for m in sorted(expected)
            ]
        sales = (
            await session.execute(
                select(
                    func.count(PosReceipt.id),
                    func.coalesce(func.sum(Order.grand_total), 0),
                )
                .select_from(PosReceipt)
                .join(Order, Order.id == PosReceipt.order_id)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.session_id == pos_session.id,
                    PosReceipt.kind == "sale",
                )
            )
        ).one()
        returns_row = (
            await session.execute(
                select(
                    func.count(func.distinct(PosReturnLine.receipt_id)),
                    func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                )
                .select_from(PosReturnLine)
                .join(PosReceipt, PosReceipt.id == PosReturnLine.receipt_id)
                .where(
                    PosReturnLine.tenant_id == tenant_id,
                    PosReceipt.session_id == pos_session.id,
                )
            )
        ).one()
        cash_rows = (
            (
                await session.execute(
                    select(PosCashMovement)
                    .where(
                        PosCashMovement.tenant_id == tenant_id,
                        PosCashMovement.session_id == pos_session.id,
                    )
                    .order_by(PosCashMovement.created_at.asc(), PosCashMovement.id.asc())
                )
            )
            .scalars()
            .all()
        )
        handovers = await PosService.list_handovers(session, tenant_id, pos_session.id)
        inflow, outflow = await PosService._cash_totals(session, tenant_id, pos_session.id)
        return {
            "session": {
                "id": str(pos_session.id),
                "register_id": str(pos_session.register_id),
                "profile_id": (
                    str(pos_session.profile_id) if pos_session.profile_id else None
                ),
                "cashier_user_id": (
                    str(pos_session.cashier_user_id)
                    if pos_session.cashier_user_id
                    else None
                ),
                "status": pos_session.status,
                "opened_at": pos_session.opened_at.isoformat(),
                "closed_at": (
                    pos_session.closed_at.isoformat() if pos_session.closed_at else None
                ),
            },
            "by_method": by_method,
            # Session-level rollups for the report header: expected sums every
            # method's target; variance exists only once the shift is counted.
            "expected_total": str(
                to_money(
                    sum((Decimal(r["expected"]) for r in by_method), Decimal("0")),
                    "expected_total",
                )
            ),
            "variance_total": (
                str(
                    to_money(
                        sum(
                            (Decimal(r["variance"]) for r in by_method if r["variance"]),
                            Decimal("0"),
                        ),
                        "variance_total",
                    )
                )
                if pos_session.status == "CLOSED"
                else None
            ),
            "opening_float": str(pos_session.opening_float),
            "cash_in": str(inflow),
            "cash_out": str(outflow),
            "sales": {
                "invoice_count": int(sales[0]),
                "total": str(to_money(sales[1], "sales")),
            },
            "returns": {
                "return_count": int(returns_row[0]),
                "total": str(to_money(returns_row[1], "returns")),
            },
            "cash_movements": [
                {
                    "direction": r.direction,
                    "reason": r.reason,
                    "amount": str(r.amount),
                    "created_at": r.created_at.isoformat(),
                }
                for r in cash_rows
            ],
            "handovers": [
                {
                    "from_user_id": str(h.from_user_id) if h.from_user_id else None,
                    "to_user_id": str(h.to_user_id),
                    "expected_cash": str(h.expected_cash),
                    "counted_cash": str(h.counted_cash),
                    "variance": str(h.variance),
                    "created_at": h.created_at.isoformat(),
                }
                for h in handovers
            ],
        }

    # ----------------------------------------------------- daily projection --

    @staticmethod
    async def upsert_daily_projection(
        session: AsyncSession, tenant_id: UUID, *, business_date: date
    ) -> int:
        """Recompute the (date, register) projection rows from the ledgers.

        Called by the pos worker on every ``pos.session.closed`` event. It
        DELETEs and re-INSERTs the day's rows rather than incrementing them,
        so a redelivered event rewrites the same truth — idempotent by
        construction (§190: an event-fed projection, never a core column).
        """
        from app.modules.orders.models import Order

        day_sessions = (
            (
                await session.execute(
                    select(PosSession).where(
                        PosSession.tenant_id == tenant_id,
                        PosSession.status == "CLOSED",
                        # The business date is the UTC calendar date — spelled
                        # out explicitly, because a bare func.date() would use
                        # the SESSION's timezone (a Cairo-zone database then
                        # disagrees with the UTC date by one day after 22:00
                        # and the projection silently projects nothing).
                        func.date(
                            func.timezone("UTC", PosSession.closed_at)
                        )
                        == business_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        await session.execute(
            delete(PosDailySales).where(
                PosDailySales.tenant_id == tenant_id,
                PosDailySales.business_date == business_date,
            )
        )
        by_register: dict[UUID, list[PosSession]] = {}
        for pos_session in day_sessions:
            by_register.setdefault(pos_session.register_id, []).append(pos_session)

        written = 0
        for register_id, sessions in by_register.items():
            session_ids = [s.id for s in sessions]
            invoice_count, sales_total, taxes_total = (
                await session.execute(
                    select(
                        func.count(PosReceipt.id),
                        func.coalesce(func.sum(Order.grand_total), 0),
                        func.coalesce(func.sum(Order.tax_total), 0),
                    )
                    .select_from(PosReceipt)
                    .join(Order, Order.id == PosReceipt.order_id)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id.in_(session_ids),
                        PosReceipt.kind == "sale",
                    )
                )
            ).one()
            returns_count, returns_total = (
                await session.execute(
                    select(
                        func.count(func.distinct(PosReturnLine.receipt_id)),
                        func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                    )
                    .select_from(PosReturnLine)
                    .join(PosReceipt, PosReceipt.id == PosReturnLine.receipt_id)
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReceipt.session_id.in_(session_ids),
                    )
                )
            ).one()
            method_rows = (
                await session.execute(
                    select(
                        PosSessionReconciliation.method,
                        func.coalesce(
                            func.sum(PosSessionReconciliation.expected_amount), 0
                        ),
                        func.coalesce(
                            func.sum(PosSessionReconciliation.counted_amount), 0
                        ),
                        func.coalesce(func.sum(PosSessionReconciliation.variance), 0),
                    )
                    .where(
                        PosSessionReconciliation.tenant_id == tenant_id,
                        PosSessionReconciliation.session_id.in_(session_ids),
                    )
                    .group_by(PosSessionReconciliation.method)
                )
            ).all()
            session.add(
                PosDailySales(
                    tenant_id=tenant_id,
                    business_date=business_date,
                    register_id=register_id,
                    session_count=len(session_ids),
                    invoice_count=int(invoice_count),
                    returns_count=int(returns_count),
                    sales_total=to_money(sales_total, "sales_total"),
                    returns_total=to_money(returns_total, "returns_total"),
                    taxes_total=to_money(taxes_total, "taxes_total"),
                    variance_total=to_money(
                        sum(
                            (Decimal(str(s.variance or 0)) for s in sessions),
                            Decimal("0"),
                        ),
                        "variance_total",
                    ),
                    by_method=[
                        {
                            "method": method,
                            "expected": str(to_money(m_expected, "expected")),
                            "counted": str(to_money(m_counted, "counted")),
                            "variance": str(to_money(m_variance, "variance")),
                        }
                        for method, m_expected, m_counted, m_variance in method_rows
                    ],
                )
            )
            written += 1
        await session.flush()
        return written

    @staticmethod
    async def sales_by_day(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        since: date,
        until: date,
    ) -> list[dict]:
        """Sales per MERCHANT day over ``[since, until]`` (inclusive), straight from the receipts.

        Same rules the shift report uses, so a day always equals the sum of its shifts: sales are
        the ``grand_total`` of ``sale`` receipts (an exchange's new sale counts as a sale, its
        return counts as a return), returns are the ``refund_total`` of the return lines, and a day
        is the shop's own calendar day (``tenants.timezone``), never UTC's. A day with no activity
        is simply absent. ``net`` = sales - returns; the discount is the order's own
        ``discount_total``. Returns are booked on the day the RETURN happened, not the sale's day.
        """
        from zoneinfo import ZoneInfo

        from app.modules.orders.models import Order, OrderItem

        tz = (await PosService._shop_timezone(session, tenant_id) or "UTC").strip() or "UTC"
        zone = ZoneInfo(tz)  # a stored zone that no longer resolves fails loudly, never as UTC
        lo = datetime(since.year, since.month, since.day, tzinfo=zone).astimezone(UTC)
        nxt = until + timedelta(days=1)
        hi = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone).astimezone(UTC)

        sale_day = func.date(func.timezone(tz, PosReceipt.issued_at))
        sales = (
            await session.execute(
                select(
                    sale_day.label("day"),
                    func.count(PosReceipt.id),
                    func.coalesce(func.sum(Order.subtotal), 0),
                    func.coalesce(func.sum(Order.discount_total), 0),
                    func.coalesce(func.sum(Order.grand_total), 0),
                )
                .select_from(PosReceipt)
                .join(Order, Order.id == PosReceipt.order_id)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.kind == "sale",
                    PosReceipt.issued_at >= lo,
                    PosReceipt.issued_at < hi,
                )
                .group_by(sale_day)
            )
        ).all()
        pieces = (
            await session.execute(
                select(
                    sale_day.label("day"),
                    func.coalesce(func.sum(OrderItem.quantity), 0),
                )
                .select_from(PosReceipt)
                .join(OrderItem, OrderItem.order_id == PosReceipt.order_id)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.kind == "sale",
                    PosReceipt.issued_at >= lo,
                    PosReceipt.issued_at < hi,
                )
                .group_by(sale_day)
            )
        ).all()
        ret_day = func.date(func.timezone(tz, PosReceipt.issued_at))
        returns = (
            await session.execute(
                select(
                    ret_day.label("day"),
                    func.count(func.distinct(PosReturnLine.receipt_id)),
                    func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                )
                .select_from(PosReturnLine)
                .join(PosReceipt, PosReceipt.id == PosReturnLine.receipt_id)
                .where(
                    PosReturnLine.tenant_id == tenant_id,
                    PosReceipt.issued_at >= lo,
                    PosReceipt.issued_at < hi,
                )
                .group_by(ret_day)
            )
        ).all()

        days: dict[date, dict] = {}

        def row(day: date) -> dict:
            return days.setdefault(
                day,
                {
                    "date": day,
                    "invoices": 0,
                    "pieces": 0,
                    "gross": Decimal("0"),
                    "discount": Decimal("0"),
                    "returns_count": 0,
                    "returns": Decimal("0"),
                },
            )

        for day, count, subtotal, discount, _grand in sales:
            r = row(day)
            r["invoices"] = int(count)
            r["gross"] = to_money(subtotal, "gross")
            r["discount"] = to_money(discount, "discount")
        for day, qty in pieces:
            row(day)["pieces"] = int(qty)
        for day, count, refunded in returns:
            r = row(day)
            r["returns_count"] = int(count)
            r["returns"] = to_money(refunded, "returns")
        # net = what was actually charged (grand total) minus what was given back.
        grand_by_day = {d: to_money(g, "grand") for d, _c, _s, _d, g in sales}
        out = []
        for day in sorted(days, reverse=True):
            r = days[day]
            net = grand_by_day.get(day, Decimal("0")) - r["returns"]
            out.append(
                {
                    "date": str(day),
                    "invoices": r["invoices"],
                    "pieces": r["pieces"],
                    "gross": str(r["gross"]),
                    "discount": str(r["discount"]),
                    "returns_count": r["returns_count"],
                    "returns": str(r["returns"]),
                    "net": str(to_money(net, "net")),
                }
            )
        return out

    @staticmethod
    async def daily_report(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        business_date: date,
        register_id: UUID | None = None,
    ) -> list[PosDailySales]:
        """The projection's read side: one row per register for the date."""
        query = select(PosDailySales).where(
            PosDailySales.tenant_id == tenant_id,
            PosDailySales.business_date == business_date,
        )
        if register_id is not None:
            query = query.where(PosDailySales.register_id == register_id)
        rows = (
            (await session.execute(query.order_by(PosDailySales.register_id.asc())))
            .scalars()
            .all()
        )
        return list(rows)

    # ------------------------------------------------------- receipt email ----

    @staticmethod
    async def request_receipt_email(
        session: AsyncSession,
        tenant_id: UUID,
        receipt_id: UUID,
        *,
        email: str,
        requested_by: UUID | None = None,
    ) -> dict:
        """Queue "email me this receipt" (ERPNext's email-receipt dialog).

        The request path NEVER sends mail: it stages a durable
        ``pos.receipt.email_requested`` event that the pos worker pool sends.
        An unconfigured deployment is refused here, up front — never retried
        in the background forever.
        """
        from app.core.config import get_settings
        from app.core.events.writer import add_outbox_event

        receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id, PosReceipt.id == receipt_id
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError(f"pos receipt {receipt_id} not found")
        if not get_settings().auth_email_delivery_configured:
            raise ValidationError("email delivery is not configured on this deployment")
        cleaned = str(email).strip()
        if "@" not in cleaned or len(cleaned) > 254 or cleaned.startswith("@"):
            raise ValidationError("a valid email address is required")

        await add_outbox_event(
            session,
            aggregate_type="pos_session",
            aggregate_id=receipt.session_id,
            event_type="pos.receipt.email_requested",
            tenant_id=tenant_id,
            payload={
                "pos.receipt.email_requested": True,
                "receipt_id": str(receipt.id),
                "session_id": str(receipt.session_id),
                "email": cleaned,
                "requested_by": str(requested_by) if requested_by else None,
            },
            producer="pos",
        )
        return {"receipt_id": receipt.id, "email": cleaned, "queued": True}

    # --------------------------------------------------------- held carts ----

    @staticmethod
    async def hold_cart(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        items: list[dict],
        customer_id: UUID | None = None,
        discount_total: object = None,
        label: str | None = None,
        held_by: UUID | None = None,
    ) -> PosHeldCart:
        """Park a basket on the OPEN session; reserve nothing, book nothing.

        A hold is a convenience for the cashier, not a sale: it validates the
        lines are shaped right (a variant id and a positive quantity) so a
        parked cart cannot rot into an unsellable one, but it deliberately does
        NOT price them, reserve them, or touch money. The price is struck at
        sell time from the tenant's ladder; a hold therefore never freezes a
        price the catalog may since have changed.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("carts are held on the open session only")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        clean_items = PosService._clean_held_items(items)
        if discount_total is not None:
            # Validated for shape now, so a bad discount is refused at hold
            # time rather than surprising the cashier hours later at sell.
            to_money(discount_total, "discount_total")
        held = PosHeldCart(
            tenant_id=tenant_id,
            session_id=session_id,
            items=clean_items,
            customer_id=customer_id,
            discount_total=(
                to_money(discount_total, "discount_total")
                if discount_total is not None
                else None
            ),
            label=(str(label).strip() or None) if label is not None else None,
            held_by_user_id=held_by,
        )
        session.add(held)
        await session.flush()
        return held

    @staticmethod
    async def list_held_carts(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> list[PosHeldCart]:
        rows = (
            (
                await session.execute(
                    select(PosHeldCart)
                    .where(
                        PosHeldCart.tenant_id == tenant_id,
                        PosHeldCart.session_id == session_id,
                    )
                    .order_by(PosHeldCart.created_at.asc(), PosHeldCart.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def get_held_cart(
        session: AsyncSession, tenant_id: UUID, held_cart_id: UUID
    ) -> PosHeldCart:
        held = (
            await session.execute(
                select(PosHeldCart).where(
                    PosHeldCart.tenant_id == tenant_id,
                    PosHeldCart.id == held_cart_id,
                )
            )
        ).scalar_one_or_none()
        if held is None:
            raise NotFoundError(f"held cart {held_cart_id} not found")
        return held

    @staticmethod
    async def release_held_cart(
        session: AsyncSession, tenant_id: UUID, held_cart_id: UUID
    ) -> None:
        """Drop a parked cart — the customer left, or it became a sale."""
        held = await PosService.get_held_cart(session, tenant_id, held_cart_id)
        await session.delete(held)

    @staticmethod
    def _clean_held_items(items: object) -> list[dict]:
        if not isinstance(items, list) or not items:
            raise ValidationError("a held cart must contain at least one item")
        clean: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValidationError("each held item must be an object")
            try:
                variant_id = UUID(str(item["variant_id"]))
            except (KeyError, ValueError):
                raise ValidationError("each held item needs a valid variant_id") from None
            quantity = PosService._positive_qty(item.get("quantity"))
            clean_item: dict = {"variant_id": str(variant_id), "quantity": quantity}
            # A held cart keeps the cashier's per-line discount exactly as
            # typed, so the resume reprices the same basket.
            pct = item.get("discount_pct")
            if pct is not None:
                # JSONB storage: the discount rides as a string, like every
                # other money figure in the tree.
                clean_item["discount_pct"] = str(PosService._line_discount_pct(item))
            clean.append(clean_item)
        return clean

    # ------------------------------------------------------------ refunds ----

    @staticmethod
    async def refund(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        order_id: UUID,
        amount: object,
        method: str = "cash",
        reason: str = "customer_return",
        restock: bool = False,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> dict:
        """Give money back on a POS sale, and optionally take the goods back.

        The refund itself is the orders ledger's job (ADR-054: a refund is a
        row against a captured payment, capped by what was captured), so this
        delegates to ``OrderService.register_refund`` per captured payment until
        the requested amount is placed. What POS adds is the drawer: a cash
        refund is money leaving THIS shift's till, so it is booked as a
        ``cash_refund`` row on the session the sale was rung on — never on
        today's session, which would make today's drawer short by a sale it
        never made.

        ``cash`` refunds require the sale's session to be the OPEN one; a
        card/wallet refund needs no open drawer at all.
        """
        from app.modules.orders.models import OrderPayment, Refund
        from app.modules.orders.service import OrderService

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; refunds ride the open drawer")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )

        receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.order_id == order_id,
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError(f"no POS receipt for order {order_id}")
        if receipt.session_id != pos_session.id:
            # A refund of another shift's sale would move money between two
            # drawers, and the reconciliation of both would then lie.
            raise ConflictError("this sale belongs to a different session")

        if method not in _SALE_METHODS:
            raise ValidationError(f"method must be one of {sorted(_SALE_METHODS)}")

        requested = _positive_amount(amount, "amount")

        # Order the captured payments so a refund fills the cash leg first
        # (the drawer is where money physically leaves), then the oldest —
        # created_at ties inside one transaction make id the tiebreaker, and
        # cash-first is what keeps the split deterministic (see return_sale).
        captured = (
            (
                await session.execute(
                    select(OrderPayment)
                    .where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id == order_id,
                        OrderPayment.status.in_(("captured", "partially_refunded")),
                    )
                    .order_by(
                        (OrderPayment.method == "cash").desc(),
                        OrderPayment.created_at.asc(),
                        OrderPayment.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

        # PLAN the legs first, then write: splitting a refund across several
        # payments must not half-succeed. If the requested amount does not fit
        # the payments' remaining headroom, refuse BEFORE the first refund row
        # exists — writing the legs and discovering the shortfall last would
        # leave a partial refund behind an error (the exact trap that turned a
        # refused 25-on-20 refund into a silent 20 that blocked the retry).
        plan: list[tuple[OrderPayment, Decimal]] = []
        remaining = requested
        for payment in captured:
            if remaining <= 0:
                break
            already = Decimal(
                str(
                    (
                        await session.execute(
                            select(func.coalesce(func.sum(Refund.amount), 0))
                            .select_from(Refund)
                            .where(
                                Refund.tenant_id == tenant_id,
                                Refund.payment_id == payment.id,
                                Refund.status != "rejected",
                            )
                        )
                    ).scalar_one()
                )
            )
            headroom = to_money(payment.amount, "captured") - already
            if headroom <= 0:
                continue
            leg = remaining if remaining <= headroom else headroom
            plan.append((payment, leg))
            remaining -= leg

        if remaining > 0:
            raise ConflictError(
                f"refund exceeds what this sale captured; "
                f"{remaining} could not be placed against its payments"
            )

        written: list[Refund] = []
        for payment, leg in plan:
            written.append(
                await OrderService.register_refund(
                    session,
                    tenant_id,
                    order_id,
                    payment.id,
                    amount=leg,
                    reason=reason,
                    by_user_id=actor_user_id,
                )
            )

        refunded_total = sum((r.amount for r in written), Decimal("0"))

        restocked = False
        if restock:
            restocked = await PosService._restock_pos_sale(
                session,
                tenant_id,
                pos_session,
                order_id,
                actor_user_id=actor_user_id,
            )

        if method == "cash" and refunded_total > 0:
            await PosService._append_sale_cash(
                session,
                tenant_id,
                pos_session.id,
                reason="cash_refund",
                amount=to_money(refunded_total, "cash_refund"),
                created_by=actor_user_id,
                reference_id=order_id,
            )

        return {
            "order_id": order_id,
            "amount": str(to_money(refunded_total, "refunded")),
            "refunds": [str(r.id) for r in written],
            "restocked": restocked,
        }

    @staticmethod
    async def _restock_pos_sale(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        order_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> bool:
        """Put a counter-returned basket back on the shelf.

        A POS sale is over-the-counter: the goods left the moment it was paid,
        so the order never reaches ``shipped``/``delivered`` and the courier
        return saga (``ReturnsService``, for parcels) does not apply. The goods
        are physically back at the till, so the honest write is a physical
        ``in`` movement with reason ``return`` against the register's warehouse
        — the same ledger every other stock event uses.

        Because a POS basket can be refunded more than once across its life, the
        restock is guarded: it runs only while the order has no prior ``return``
        movement for it, so a double refund cannot double-count the goods.
        """
        from app.modules.inventory.models import InventoryMovement
        from app.modules.inventory.service import InventoryService
        from app.modules.orders.models import OrderItem

        already = (
            await session.execute(
                select(InventoryMovement.id)
                .where(
                    InventoryMovement.tenant_id == tenant_id,
                    InventoryMovement.reason == "return",
                    InventoryMovement.reference_type == "order",
                    InventoryMovement.reference_id == order_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if already is not None:
            # Goods already back — the money refund is still honoured, the
            # shelf is not touched twice.
            return True

        register = await PosService._get_register(session, tenant_id, pos_session.register_id)
        lines = (
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == order_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for line in sorted(lines, key=lambda item: item.variant_id):
            await InventoryService.move(
                session,
                tenant_id,
                line.variant_id,
                register.warehouse_id,
                direction="in",
                quantity=line.quantity,
                reason="return",
                reference_type="order",
                reference_id=order_id,
            )
        return True

    # ------------------------------------------------------------- returns ----

    @staticmethod
    def _return_line_totals(
        order_subtotal: Decimal,
        order_discount: Decimal,
        lines: list[tuple[Decimal, int]] | list[tuple[Decimal, int, Decimal]],
        *,
        sold_net_subtotal: Decimal | None = None,
    ) -> list[Decimal]:
        """Each returned line's refund, in the original sale's prices (pure).

        A line is ``(unit_price, quantity)``, or ``(unit_price, quantity, line_pct)`` when the
        cashier typed a per-line discount. The refund starts from what the customer actually PAID
        for the line: its gross minus ITS OWN line discount. Only the order-level discount (what is
        left of ``order_discount`` after every line discount) is shared out in proportion, over the
        NET of the lines. Treating the line discount as part of one basket-wide discount (the old
        rule) refunded a 50%-off item at 75 when 50 was paid.

        ``sold_net_subtotal`` is the order's gross minus ALL its line discounts. Without it every
        line is assumed to carry no line discount (the pair form), exactly as before.
        Rounding is per line, HALF_UP to the money quantum, the same precision the sale priced with.
        """
        money = Decimal("0.01")
        net_base = order_subtotal if sold_net_subtotal is None else sold_net_subtotal
        order_level = max(order_discount - (order_subtotal - net_base), Decimal("0"))
        refunds: list[Decimal] = []
        for entry in lines:
            unit_price, quantity = entry[0], entry[1]
            pct = Decimal(str(entry[2])) if len(entry) > 2 else Decimal("0")
            gross = to_money(unit_price, "unit_price") * quantity
            net = (gross - gross * pct / Decimal("100")).quantize(money, rounding=ROUND_HALF_UP)
            share = Decimal("0")
            if net_base > 0 and order_level > 0:
                share = (order_level * net / net_base).quantize(money, rounding=ROUND_HALF_UP)
            refunds.append(to_money(net - share, "refund_total"))
        return refunds

    @staticmethod
    async def return_sale(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        order_id: UUID,
        lines: list[dict],
        restock: bool = False,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
        ceiling_override: bool = False,
    ) -> dict:
        """Give goods AND money back, line by line (ERPNext's POS return).

        The return is a document against the original sale: each line is
        capped at sold-minus-already-returned, priced at the ORIGINAL line's
        unit price minus its discount share, and the money travels through the
        ORIGINAL captured tenders — the customer is made whole the way they
        paid. ``restock`` also puts the returned quantities back on the
        register's shelf. A return receipt (``POS-RET-``) is issued and the
        returned lines are recorded on it, which is what every later return
        caps against.
        """
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.models import InventoryMovement
        from app.modules.inventory.service import InventoryService
        from app.modules.orders.models import Order, OrderItem, OrderPayment, Refund
        from app.modules.orders.service import OrderService

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; returns ride the open drawer")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        if not lines:
            raise ValidationError("a return must contain at least one line")

        # The original sale's receipt, rung on THIS drawer.
        receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.order_id == order_id,
                    PosReceipt.kind == "sale",
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError(f"no POS sale receipt for order {order_id}")
        # The sale may have been rung on an EARLIER shift, even one already counted and closed: the
        # customer comes back tomorrow. Quantities and prices are checked against the ORIGINAL sale
        # (below); the money leaves the drawer that is open NOW. Booking it on the old shift would
        # change a closed, counted report after the fact.

        # Requested quantities, merged per variant (a customer may hand back
        # the same SKU twice in one return).
        requested: dict[UUID, int] = {}
        for line in lines:
            try:
                variant_id = UUID(str(line["variant_id"]))
                quantity = PosService._positive_qty(line.get("quantity"))
            except (KeyError, TypeError, ValueError):
                raise ValidationError(
                    "each return line needs a variant_id and a positive quantity"
                ) from None
            requested[variant_id] = requested.get(variant_id, 0) + quantity

        # Serialise returns of ONE sale. The cap below is "sold minus already returned": read,
        # decide, write. Without a lock two returns of the last unit both read "0 returned" and
        # both pass; the money is only saved later by the payment-row cap, which fires late
        # (after the drawer and the shelf were touched). The row lock makes the second one wait,
        # then see the first one's lines and refuse on the quantity.
        order = (
            await session.execute(
                select(Order)
                .where(Order.tenant_id == tenant_id, Order.id == order_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError(f"order {order_id} not found")

        sold: dict[UUID, dict] = {}
        sold_net = Decimal("0")
        for item in (
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == order_id,
                    )
                )
            )
            .scalars()
            .all()
        ):
            entry = sold.setdefault(
                item.variant_id, {"quantity": 0, "unit_price": None, "line_pct": Decimal("0")}
            )
            entry["quantity"] += item.quantity
            if entry["unit_price"] is None:
                entry["unit_price"] = to_money(item.unit_price, "unit_price")
                entry["line_pct"] = Decimal(str(item.discount_pct or 0))
            sold_net += Decimal(str(item.total))

        unknown = set(requested) - set(sold)
        if unknown:
            raise ValidationError(
                f"{len(unknown)} returned variant(s) were never sold on this order"
            )

        # The money cap: a variant cannot come back more times than it sold.
        already_returned = dict(
            (
                await session.execute(
                    select(
                        PosReturnLine.variant_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                    )
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReturnLine.order_id == order_id,
                    )
                    .group_by(PosReturnLine.variant_id)
                )
            ).all()
        )
        for variant_id, quantity in requested.items():
            sold_qty = sold[variant_id]["quantity"]
            money_cap = sold_qty - int(already_returned.get(variant_id, 0))
            if quantity > money_cap:
                raise ConflictError(
                    f"variant {variant_id} was sold {sold_qty} and "
                    f"{money_cap} unit(s) are already returned"
                )

        if restock:
            # The goods cap, separate from the money cap: a money-only return
            # consumed no shelf space, and goods already back cannot come back
            # twice.
            restocked_already = dict(
                (
                    await session.execute(
                        select(
                            InventoryMovement.variant_id,
                            func.coalesce(func.sum(InventoryMovement.quantity), 0),
                        )
                        .where(
                            InventoryMovement.tenant_id == tenant_id,
                            InventoryMovement.reason == "return",
                            InventoryMovement.reference_type == "order",
                            InventoryMovement.reference_id == order_id,
                        )
                        .group_by(InventoryMovement.variant_id)
                    )
                ).all()
            )
            for variant_id, quantity in requested.items():
                goods_cap = sold[variant_id]["quantity"] - int(
                    restocked_already.get(variant_id, 0)
                )
                if quantity > goods_cap:
                    raise ConflictError(
                        f"variant {variant_id}: only {goods_cap} unit(s) of this sale "
                        "are still out of the shelf"
                    )

        # Price the return at the ORIGINAL sale's own numbers.
        priced = PosService._return_line_totals(
            Decimal(str(order.subtotal)),
            Decimal(str(order.discount_total)),
            [(sold[v]["unit_price"], requested[v], sold[v]["line_pct"]) for v in requested],
            sold_net_subtotal=sold_net,
        )
        refund_lines = [
            {
                "variant_id": variant_id,
                "quantity": requested[variant_id],
                "unit_price": sold[variant_id]["unit_price"],
                "refund_total": total,
            }
            for variant_id, total in zip(requested, priced, strict=True)
        ]
        refund_total = to_money(
            sum((entry["refund_total"] for entry in refund_lines), Decimal("0")),
            "refund_total",
        )
        # The owner's limit on what a cashier may hand back alone. Checked once the amount is known
        # and BEFORE the drawer, the shelf or any ledger is touched.
        PosProfileService.ensure_within_money_ceiling(
            await PosService.resolve_profile(session, tenant_id, pos_session),
            refund_total,
            kind="refund",
            approved=ceiling_override,
        )

        # Allocate the money across the ORIGINAL captured tenders — cash
        # absorbs first (the drawer is where a refund physically leaves from),
        # then oldest first. created_at alone cannot order rows written in ONE
        # transaction (they share the transaction timestamp), so cash-first is
        # the deterministic rule that keeps refunds off the wrong tender.
        captured = (
            (
                await session.execute(
                    select(OrderPayment)
                    .where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id == order_id,
                        OrderPayment.status.in_(("captured", "partially_refunded")),
                    )
                    .order_by(
                        (OrderPayment.method == "cash").desc(),
                        OrderPayment.created_at.asc(),
                        OrderPayment.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        plan: list[tuple[OrderPayment, Decimal]] = []
        remaining = refund_total
        for payment in captured:
            if remaining <= 0:
                break
            already = Decimal(
                str(
                    (
                        await session.execute(
                            select(func.coalesce(func.sum(Refund.amount), 0))
                            .select_from(Refund)
                            .where(
                                Refund.tenant_id == tenant_id,
                                Refund.payment_id == payment.id,
                                Refund.status != "rejected",
                            )
                        )
                    ).scalar_one()
                )
            )
            headroom = to_money(payment.amount, "captured") - already
            if headroom <= 0:
                continue
            leg = remaining if remaining <= headroom else headroom
            plan.append((payment, leg))
            remaining -= leg
        if remaining > 0:
            raise ConflictError(
                f"return exceeds what this sale captured; "
                f"{remaining} could not be placed against its payments"
            )

        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        allowed_return_methods = (
            set(profile.returns_allowed_methods or []) if profile is not None else set()
        )
        if allowed_return_methods:
            refused = {payment.method for payment, _leg in plan} - allowed_return_methods
            if refused:
                raise ValidationError(
                    f"refund methods {sorted(refused)} are not enabled for "
                    "returns on this profile"
                )

        written: list[Refund] = []
        for payment, leg in plan:
            written.append(
                await OrderService.register_refund(
                    session,
                    tenant_id,
                    order_id,
                    payment.id,
                    amount=leg,
                    reason="pos_return",
                    by_user_id=actor_user_id,
                )
            )
        cash_legs = sum(
            (leg for payment, leg in plan if payment.method == "cash"), Decimal("0")
        )
        if cash_legs > 0:
            await PosService._append_sale_cash(
                session,
                tenant_id,
                pos_session.id,
                reason="cash_refund",
                amount=to_money(cash_legs, "cash_refund"),
                created_by=actor_user_id,
                reference_id=order_id,
            )

        restocked = False
        if restock:
            register = await PosService._get_register(
                session, tenant_id, pos_session.register_id
            )
            for entry in refund_lines:
                await InventoryService.move(
                    session,
                    tenant_id,
                    entry["variant_id"],
                    register.warehouse_id,
                    direction="in",
                    quantity=entry["quantity"],
                    reason="return",
                    reference_type="order",
                    reference_id=order_id,
                )
            restocked = True

        return_receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            number_prefix="POS-RET",
            kind="return",
        )
        for entry in refund_lines:
            session.add(
                PosReturnLine(
                    tenant_id=tenant_id,
                    receipt_id=return_receipt.id,
                    order_id=order_id,
                    variant_id=entry["variant_id"],
                    quantity=entry["quantity"],
                    unit_price=entry["unit_price"],
                    refund_total=entry["refund_total"],
                )
            )
        await session.flush()

        await add_outbox_event(
            session,
            aggregate_type="pos_session",
            aggregate_id=pos_session.id,
            event_type="pos.sale.returned",
            tenant_id=tenant_id,
            payload={
                "pos.sale.returned": True,
                "session_id": str(pos_session.id),
                "order_id": str(order_id),
                "receipt_id": str(return_receipt.id),
                "refunded_total": str(refund_total),
                "by_method": [
                    {"method": payment.method, "amount": str(leg)}
                    for payment, leg in plan
                ],
                "restocked": restocked,
            },
            producer="pos",
        )
        return {
            "receipt_id": return_receipt.id,
            "receipt_number": return_receipt.number,
            "refunded_total": str(refund_total),
            "by_method": [
                {"method": payment.method, "amount": str(leg)} for payment, leg in plan
            ],
            "lines": [
                {
                    "variant_id": str(entry["variant_id"]),
                    "quantity": entry["quantity"],
                    "refund_total": str(entry["refund_total"]),
                }
                for entry in refund_lines
            ],
            "restocked": restocked,
        }

    # ----------------------------------------------------------- exchanges ----

    @staticmethod
    async def exchange(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        order_id: UUID,
        return_lines: list[dict],
        new_lines: list[dict],
        restock: bool = True,
        tenders: list[dict] | None = None,
        method: str | None = None,
        amount: object | None = None,
        tendered_cash: object | None = None,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> dict:
        """The one-transaction exchange (§189 — beyond ERPNext and Odoo).

        The customer's return funds its own replacement: the return value is
        first credited against the ORIGINAL captured tenders (cash-first),
        the credit pays the new order, and only the leftover — if the return
        was worth more than the replacement — is actually refunded (cash
        legs physically leave the drawer; card legs are ledger rows). When
        the replacement costs more, the customer is charged just the
        difference through the caller's tenders. Either way the return and
        the new sale commit together or not at all, under two receipts.

        The exchange keeps the original order's customer, and the new lines
        are priced off the CURRENT ladder with no discount (v1).
        """
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.models import InventoryMovement
        from app.modules.inventory.service import InventoryService
        from app.modules.orders.models import Order, OrderItem, OrderPayment, Refund
        from app.modules.orders.service import OrderService

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; exchanges ride the open drawer")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        if not return_lines:
            raise ValidationError("an exchange must return at least one line")
        if not new_lines:
            raise ValidationError("an exchange must replace with at least one line")

        # ---------- the return half: identical rules to return_sale -----------
        receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.order_id == order_id,
                    PosReceipt.kind == "sale",
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError(f"no POS sale receipt for order {order_id}")
        # As in return_sale: the original sale may be on an earlier, closed shift. The goods are
        # checked against that sale; the money moves on the shift that is open now.

        requested: dict[UUID, int] = {}
        for line in return_lines:
            try:
                variant_id = UUID(str(line["variant_id"]))
                quantity = PosService._positive_qty(line.get("quantity"))
            except (KeyError, TypeError, ValueError):
                raise ValidationError(
                    "each return line needs a variant_id and a positive quantity"
                ) from None
            requested[variant_id] = requested.get(variant_id, 0) + quantity

        # Serialise returns of ONE sale. The cap below is "sold minus already returned": read,
        # decide, write. Without a lock two returns of the last unit both read "0 returned" and
        # both pass; the money is only saved later by the payment-row cap, which fires late
        # (after the drawer and the shelf were touched). The row lock makes the second one wait,
        # then see the first one's lines and refuse on the quantity.
        order = (
            await session.execute(
                select(Order)
                .where(Order.tenant_id == tenant_id, Order.id == order_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError(f"order {order_id} not found")

        sold: dict[UUID, dict] = {}
        sold_net = Decimal("0")
        for item in (
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == order_id,
                    )
                )
            )
            .scalars()
            .all()
        ):
            entry = sold.setdefault(
                item.variant_id, {"quantity": 0, "unit_price": None, "line_pct": Decimal("0")}
            )
            entry["quantity"] += item.quantity
            if entry["unit_price"] is None:
                entry["unit_price"] = to_money(item.unit_price, "unit_price")
                entry["line_pct"] = Decimal(str(item.discount_pct or 0))
            sold_net += Decimal(str(item.total))

        unknown = set(requested) - set(sold)
        if unknown:
            raise ValidationError(
                f"{len(unknown)} returned variant(s) were never sold on this order"
            )
        already_returned = dict(
            (
                await session.execute(
                    select(
                        PosReturnLine.variant_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                    )
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReturnLine.order_id == order_id,
                    )
                    .group_by(PosReturnLine.variant_id)
                )
            ).all()
        )
        for variant_id, quantity in requested.items():
            sold_qty = sold[variant_id]["quantity"]
            money_cap = sold_qty - int(already_returned.get(variant_id, 0))
            if quantity > money_cap:
                raise ConflictError(
                    f"variant {variant_id} was sold {sold_qty} and "
                    f"{money_cap} unit(s) are already returned"
                )
        if restock:
            restocked_already = dict(
                (
                    await session.execute(
                        select(
                            InventoryMovement.variant_id,
                            func.coalesce(func.sum(InventoryMovement.quantity), 0),
                        )
                        .where(
                            InventoryMovement.tenant_id == tenant_id,
                            InventoryMovement.reason == "return",
                            InventoryMovement.reference_type == "order",
                            InventoryMovement.reference_id == order_id,
                        )
                        .group_by(InventoryMovement.variant_id)
                    )
                ).all()
            )
            for variant_id, quantity in requested.items():
                goods_cap = sold[variant_id]["quantity"] - int(
                    restocked_already.get(variant_id, 0)
                )
                if quantity > goods_cap:
                    raise ConflictError(
                        f"variant {variant_id}: only {goods_cap} unit(s) of this sale "
                        "are still out of the shelf"
                    )

        priced = PosService._return_line_totals(
            Decimal(str(order.subtotal)),
            Decimal(str(order.discount_total)),
            [(sold[v]["unit_price"], requested[v], sold[v]["line_pct"]) for v in requested],
            sold_net_subtotal=sold_net,
        )
        return_entries = [
            {
                "variant_id": variant_id,
                "quantity": requested[variant_id],
                "unit_price": sold[variant_id]["unit_price"],
                "refund_total": total,
            }
            for variant_id, total in zip(requested, priced, strict=True)
        ]
        return_total = to_money(
            sum((e["refund_total"] for e in return_entries), Decimal("0")),
            "return_total",
        )

        # ---------- the new half: the original order's own customer ----------
        await PosService._ensure_cart_in_scope(session, tenant_id, pos_session, new_lines)
        new_subtotal, _prepared, new_line_discounts = await PosService._price_lines(
            session, tenant_id, new_lines
        )
        try:
            totals = compute_totals(
                subtotal=new_subtotal,
                discount=new_line_discounts if new_line_discounts else None,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        new_grand_total = to_money(totals["grand_total"], "new_grand_total")

        # ---------- credit the return across the original tenders -----------
        captured = (
            (
                await session.execute(
                    select(OrderPayment)
                    .where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id == order_id,
                        OrderPayment.status.in_(("captured", "partially_refunded")),
                    )
                    .order_by(
                        (OrderPayment.method == "cash").desc(),
                        OrderPayment.created_at.asc(),
                        OrderPayment.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        plan: list[tuple[OrderPayment, Decimal]] = []
        remaining = return_total
        for payment in captured:
            if remaining <= 0:
                break
            already = Decimal(
                str(
                    (
                        await session.execute(
                            select(func.coalesce(func.sum(Refund.amount), 0))
                            .select_from(Refund)
                            .where(
                                Refund.tenant_id == tenant_id,
                                Refund.payment_id == payment.id,
                                Refund.status != "rejected",
                            )
                        )
                    ).scalar_one()
                )
            )
            headroom = to_money(payment.amount, "captured") - already
            if headroom <= 0:
                continue
            leg = remaining if remaining <= headroom else headroom
            plan.append((payment, leg))
            remaining -= leg
        if remaining > 0:
            raise ConflictError(
                f"return exceeds what this sale captured; "
                f"{remaining} could not be placed against its payments"
            )

        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        allowed_return_methods = (
            set(profile.returns_allowed_methods or []) if profile is not None else set()
        )
        refund_methods = {payment.method for payment, _leg in plan}
        if allowed_return_methods and refund_methods - allowed_return_methods:
            raise ValidationError(
                f"refund methods {sorted(refund_methods - allowed_return_methods)} "
                "are not enabled for returns on this profile"
            )

        # ---------- double-entry conversion of the credit --------------------
        # The FULL return value is refunded across the original tenders
        # (cash-first), and the replacement is paid FROM that credit — funding
        # walks the legs in REVERSE (non-cash first) so physical cash never
        # moves for a pure swap: the card sees its refund and re-charge, the
        # drawer's two ledger legs cancel, and only the true net difference
        # ever moves. The refund legs and the funding payments are the
        # double-entry pair; recording only their net would leave the
        # per-method reconciliation describing money that never flowed.
        for payment, leg in plan:
            await OrderService.register_refund(
                session, tenant_id, order_id, payment.id,
                amount=leg, reason="pos_exchange", by_user_id=actor_user_id,
            )
        cash_out = sum(
            (leg for payment, leg in plan if payment.method == "cash"),
            Decimal("0"),
        )
        if cash_out > 0:
            await PosService._append_sale_cash(
                session, tenant_id, pos_session.id,
                reason="cash_refund", amount=to_money(cash_out, "cash_refund"),
                created_by=actor_user_id, reference_id=order_id,
            )
        funding: list[tuple[str, Decimal]] = []
        remaining_new = new_grand_total
        for payment, leg in reversed(plan):  # non-cash first: keep cash physical
            take = min(remaining_new, leg)
            if take > 0:
                funding.append((payment.method, take))
                remaining_new -= take
        remaining_new = to_money(remaining_new, "remaining_new")

        # The difference the customer still owes: charged through the caller's
        # tenders, which must total it exactly — the exchange's own variant of
        # the settle-the-whole-order rule.
        caller_tenders: list[dict] = []
        if remaining_new > 0:
            caller_tenders = PosService._normalise_tenders(
                tenders, method, amount,
                default_method=(
                    profile.default_payment_method if profile is not None else None
                ) or "cash",
            )
            if profile is not None:
                PosService._ensure_methods_allowed(profile, caller_tenders)
            named_all = all(t["amount"] is not None for t in caller_tenders)
            if named_all:
                tendered_total = to_money(
                    sum(
                        (t["amount"] for t in caller_tenders if t["amount"] is not None),
                        Decimal("0"),
                    ),
                    "tenders",
                )
                if tendered_total != remaining_new:
                    raise ValidationError(
                        f"tenders total {tendered_total} but the exchange "
                        f"difference is {remaining_new}"
                    )

        # ---------- commit: order, payments, receipts ------------------------
        register = await PosService._get_register(
            session, tenant_id, pos_session.register_id
        )
        new_order = await OrderService.create_order(
            session,
            tenant_id,
            order.customer_id,  # the exchange keeps the original customer
            new_lines,
            channel="pos",
            warehouse_id=register.warehouse_id,
        )
        resolved = [
            {
                "method": t["method"],
                "amount": t["amount"] if t["amount"] is not None else remaining_new,
            }
            for t in caller_tenders
        ]
        for t_method, t_amount in funding:
            await OrderService.add_payment(
                session, tenant_id, new_order.id, method=t_method, amount=t_amount,
            )
        for t in resolved:
            await OrderService.add_payment(
                session, tenant_id, new_order.id, method=t["method"], amount=t["amount"],
            )
        funding_cash = sum((amt for m, amt in funding if m == "cash"), Decimal("0"))
        caller_cash = sum(
            (t["amount"] for t in resolved if t["method"] == "cash"), Decimal("0")
        )
        # The drawer books BOTH the funding echo and the caller's physical
        # cash — but tendered/change describe the CUSTOMER's handover only:
        # the funding leg is ledger conversion, never money the till counted.
        cash_in = funding_cash + caller_cash
        if cash_in > 0:
            await PosService._append_sale_cash(
                session, tenant_id, pos_session.id,
                reason="cash_sale", amount=to_money(cash_in, "cash_in"),
                created_by=actor_user_id, reference_id=new_order.id,
            )
        tendered, change = (
            PosService._settle_change(caller_cash, tendered_cash)
            if caller_cash > 0
            else (None, None)
        )

        if restock:
            for entry in return_entries:
                await InventoryService.move(
                    session, tenant_id, entry["variant_id"], register.warehouse_id,
                    direction="in", quantity=entry["quantity"],
                    reason="return", reference_type="order", reference_id=order_id,
                )

        return_receipt = await PosService._issue_receipt(
            session, tenant_id, pos_session, order,
            number_prefix="POS-RET", kind="return",
        )
        for entry in return_entries:
            session.add(
                PosReturnLine(
                    tenant_id=tenant_id,
                    receipt_id=return_receipt.id,
                    order_id=order_id,
                    variant_id=entry["variant_id"],
                    quantity=entry["quantity"],
                    unit_price=entry["unit_price"],
                    refund_total=entry["refund_total"],
                )
            )
        new_receipt = await PosService._issue_receipt(
            session, tenant_id, pos_session, new_order,
            tendered_amount=tendered, change_amount=change,
            exchange_return_receipt_id=return_receipt.id,  # the stored pairing
        )
        await session.flush()

        net = to_money(new_grand_total - return_total, "net")
        await add_outbox_event(
            session,
            aggregate_type="pos_session",
            aggregate_id=pos_session.id,
            event_type="pos.sale.exchanged",
            tenant_id=tenant_id,
            payload={
                "pos.sale.exchanged": True,
                "session_id": str(pos_session.id),
                "order_id": str(order_id),
                "new_order_id": str(new_order.id),
                "return_receipt_id": str(return_receipt.id),
                "new_receipt_id": str(new_receipt.id),
                "return_total": str(return_total),
                "new_total": str(new_grand_total),
                "net": str(net),
                "restocked": restock,
            },
            producer="pos",
        )
        return {
            "return_receipt_id": return_receipt.id,
            "return_receipt_number": return_receipt.number,
            "new_receipt_id": new_receipt.id,
            "new_receipt_number": new_receipt.number,
            "return_total": str(return_total),
            "new_total": str(new_grand_total),
            "net": str(net),
            "by_method": [
                {"method": payment.method, "amount": str(leg)}
                for payment, leg in plan
            ] or [
                {"method": t["method"], "amount": str(t["amount"])}
                for t in resolved
            ],
            "restocked": restock,
        }

    # --------------------------------------------------------- handovers ----

    @staticmethod
    async def handover_session(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        to_user_id: UUID,
        counted_cash: object,
        by_user_id: UUID | None = None,
        note: str | None = None,
    ) -> PosSessionHandover:
        """Hand the OPEN drawer to another cashier, counting it at the seam.

        The session keeps running — only its ``cashier_user_id`` moves — so the
        close reconciliation still covers the whole shift while this row records
        who was answerable between which two points. The drawer is counted here
        for the same reason it is counted at close: a variance must belong to the
        cashier who was holding it, not be discovered later and pinned on whoever
        happens to be standing there when the shift ends.

        The new holder must be allowed to operate the session's profile, exactly
        like an opening cashier — a hand-off is not a way around the grant.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("the drawer must be open to hand it over")
        if to_user_id == pos_session.cashier_user_id:
            raise ConflictError("this user already holds the drawer")

        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        if profile is not None and not await PosProfileService.can_operate(
            session, tenant_id, profile.id, to_user_id
        ):
            raise ConflictError("this user does not operate this POS profile")

        # The drawer changes hands, so the one-open-drawer-per-cashier rule
        # applies to the receiver exactly as it did at open time.
        held_elsewhere = (
            await session.execute(
                select(PosSession.id).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.cashier_user_id == to_user_id,
                    PosSession.status == "OPEN",
                    PosSession.id != pos_session.id,
                )
            )
        ).scalar_one_or_none()
        if held_elsewhere is not None:
            raise ConflictError(
                "this user already holds another open drawer; close it or hand it over first"
            )

        counted = to_money(counted_cash, "counted_cash")
        if counted < 0:
            raise ValidationError("counted_cash must not be negative")
        inflow, outflow = await PosService._cash_totals(session, tenant_id, pos_session.id)
        expected = Decimal(pos_session.opening_float) + inflow - outflow

        from_user_id = pos_session.cashier_user_id or by_user_id
        row = PosSessionHandover(
            tenant_id=tenant_id,
            session_id=pos_session.id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            expected_cash=expected,
            counted_cash=counted,
            variance=counted - expected,
            note=(str(note).strip() or None) if note is not None else None,
        )
        session.add(row)
        # The SAME session keeps running under the new holder.
        pos_session.cashier_user_id = to_user_id
        await session.flush()
        return row

    @staticmethod
    async def list_handovers(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> list[PosSessionHandover]:
        rows = (
            (
                await session.execute(
                    select(PosSessionHandover)
                    .where(
                        PosSessionHandover.tenant_id == tenant_id,
                        PosSessionHandover.session_id == session_id,
                    )
                    .order_by(
                        PosSessionHandover.created_at.asc(), PosSessionHandover.id.asc()
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


