"""POS domain service — the cashier's RECORD of the day (§189).

The POS records sales, returns and exchanges (items, prices, discounts, invoice value, employee,
time) and updates stock. It does not take payment or move money: no tender, no change, no drawer
count, no refund. The POS says "make me a sale"; it never says "decrement stock": a sell is
CreateOrder → the §140 reservation machinery settles the stock, exactly as a WhatsApp order
would. This module owns profiles, registers, sessions, receipts and the day's closing balance
(opening balance + invoices − returns). Older cash rows and per-method counts stay readable as
history.

The scan path is the §179 entry point — a barcode (or any identifier) resolves
through ``CatalogService.resolve_identifier`` to exactly one active variant, and
the POS prices it with ``CatalogService.price_for``. A scan never invents a
product or a price.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
)
from app.modules.pos.profiles import PosProfileService

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
    async def _get_session(
        session: AsyncSession, tenant_id: UUID, session_id: UUID, *, lock: bool = False
    ) -> PosSession:
        """``lock`` takes the day's row ``FOR UPDATE``: sales, returns, exchanges and the close
        all queue on it, so a close can never compute its balance while an invoice of the same
        day is still being recorded (and a sale that waits behind a close finds it CLOSED)."""
        stmt = select(PosSession).where(
            PosSession.tenant_id == tenant_id,
            PosSession.id == session_id,
        )
        if lock:
            # ``populate_existing``: the row may already sit in this session's identity map from a
            # read taken BEFORE the lock was granted; after waiting, the fresh row must win.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        pos_session = (await session.execute(stmt)).scalar_one_or_none()
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
    async def _ensure_may_operate(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        actor_user_id: UUID | None,
        *,
        override: bool = False,
    ) -> None:
        """The ONE profile check every till operation goes through (sell, return, exchange, close).

        A profile that names its operators is restricted to them, not just at the moment the day
        is started: whoever is not granted cannot use a day somebody else opened. An ungranted
        profile stays open to every ``orders:write`` holder, and ``pos:override`` (a manager
        covering the till) passes. An unknown actor is only an internal caller; HTTP always
        supplies the user.
        """
        if override or actor_user_id is None or pos_session.profile_id is None:
            return
        if not await PosProfileService.can_operate(
            session, tenant_id, pos_session.profile_id, actor_user_id
        ):
            raise PermissionDeniedError("this user does not operate this POS profile")

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
        expected_now = (await PosService._day_totals(session, tenant_id, pos_session))[
            "closing_balance"
        ]
        floats = (
            (
                await session.execute(
                    select(PosSessionFloat).where(
                        PosSessionFloat.tenant_id == tenant_id,
                        PosSessionFloat.session_id == pos_session.id,
                    )
                )
            )
            .scalars()
            .all()
        )
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
        """HISTORY only: the in/out totals of the old cash-drawer rows of a session.

        Nothing writes those rows any more (the POS does not move money), so for a current day
        both figures are zero. Older sessions keep theirs, and the closing screen still shows
        them. Never use this to compute a balance: that is ``_day_totals``.
        """
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
        actor_user_id: UUID | None = None,
        override: bool = False,
    ) -> dict:
        """§179 THE scan entry point — an identifier resolves to one variant.

        Read-only: it resolves the variant, confirms the product is sellable and
        prices it off the tenant's ladder. An unknown code resolves to nothing
        (``found: False``) rather than a half-answer, so the till can beep
        without a 404.
        """
        from app.modules.catalog.service import CatalogService
        from app.modules.orders.service import line_title, sellable_refusal

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=override
        )
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
            product is None or product.category_id is None or str(product.category_id) not in scope
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
            "title": line_title(product.title if product else None, variant.title),
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
        from app.modules.catalog.models import Product, ProductIdentifier, ProductVariant
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
            from app.core.sql import arabic_regex

            # Arabic-tolerant: "احمر" finds "أحمر", "حقيبه" finds "حقيبة" (see core.sql).
            spelled = arabic_regex(needle)
            conditions.append(
                or_(
                    ProductVariant.title.op("~*")(spelled),
                    ProductVariant.sku.op("~*")(spelled),
                    Product.title.op("~*")(spelled),
                    ProductVariant.id.in_(
                        select(ProductIdentifier.variant_id).where(
                            ProductIdentifier.tenant_id == tenant_id,
                            ProductIdentifier.value.op("~*")(spelled),
                        )
                    ),
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
        from app.modules.orders.service import line_title

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
                    "title": line_title(product_title, variant.title),
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
        actor_user_id: UUID | None = None,
        override: bool = False,
    ) -> dict:
        """Price a cart WITHOUT writing anything — what the till shows the customer.

        The same ``compute_totals`` the order will use, so the number on screen
        is the number charged. Line discounts (§189: the cashier types a
        percentage on a piece) compose with the caller's invoice-level
        discount into one discount_total — no approval gate: a ground-shop
        discount is the cashier's call.
        """

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=override
        )
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; open a new one to quote")
        PosService._ensure_session_current(
            pos_session, tz=await PosService._shop_timezone(session, tenant_id)
        )
        if not items:
            raise ValidationError("a quote must contain at least one item")

        await PosService._ensure_cart_in_scope(session, tenant_id, pos_session, items)
        subtotal, _lines, line_discounts = await PosService._price_lines(session, tenant_id, items)
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
        """A whole, positive number of pieces. ``1.9`` is refused, never silently cut to ``1``."""
        if isinstance(value, bool) or value is None:
            raise ValidationError("quantity must be a positive integer")
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise ValidationError("quantity must be a positive integer") from None
        if not number.is_finite() or number != number.to_integral_value():
            raise ValidationError("quantity must be a whole number")
        quantity = int(number)
        if quantity <= 0:
            raise ValidationError("quantity must be greater than zero")
        return quantity

    # --------------------------------------------------------------- sell ----

    @staticmethod
    async def _today_session(
        session: AsyncSession, tenant_id: UUID, register: PosRegister
    ) -> PosSession | None:
        """The register's OPEN session for today, or None when the day has not been started.

        Read-only apart from one thing: a session left open from a previous merchant day is
        closed through the normal close (its closing balance is computed from the invoices and
        returns and stored, and the close event is emitted) and None is returned, so the next
        sale cannot happen until a new day is started.
        """
        tz = await PosService._shop_timezone(session, tenant_id)
        current = (
            await session.execute(
                select(PosSession).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.register_id == register.id,
                    PosSession.status == "OPEN",
                )
            )
        ).scalar_one_or_none()
        if current is None:
            return None
        try:
            PosService._ensure_session_current(current, tz=tz)
            return current
        except ConflictError:
            # Nobody closed that day by hand: close it the SAME way, so it keeps its closing
            # balance and announces ``pos.session.closed`` like any other close. Re-read the day
            # FOR UPDATE first: a sale or a held cart that is mid-flight finishes before this
            # close, and a caller that lost the race finds the day already CLOSED and does nothing.
            locked = await PosService._get_session(session, tenant_id, current.id, lock=True)
            if locked.status == "OPEN":
                await PosService._record_close(session, tenant_id, locked, closed_by=None)
            return None

    @staticmethod
    async def working_session(
        session: AsyncSession, tenant_id: UUID, register_id: UUID
    ) -> PosSession | None:
        """Today's session for a register, or None when the day has not been started."""
        register = await PosService._get_register(session, tenant_id, register_id)
        if not register.is_active:
            raise ConflictError(f"register {register.code} is not active")
        return await PosService._today_session(session, tenant_id, register)

    @staticmethod
    async def open_day(
        session: AsyncSession,
        tenant_id: UUID,
        register_id: UUID,
        *,
        opening_float: object,
        actor_user_id: UUID | None = None,
    ) -> PosSession:
        """Start the trading day: the drawer's real balance, entered by the employee.

        The opening balance is required. There is no default and no zero-by-omission: a day
        with no balance is a day whose closing count means nothing. Opening twice returns the
        day already open, unchanged (the first figure stands), so a double tap or a second
        cashier on the same till cannot overwrite it. Concurrent first calls race on the
        ``uq_pos_sessions_open_per_register`` index and the loser reads the winner's row.
        """
        if opening_float is None or str(opening_float).strip() == "":
            raise ValidationError("opening_float is required to start the day")
        opening = to_money(opening_float, "opening_float")
        if opening < 0:
            raise ValidationError("opening_float must not be negative")
        register = await PosService._get_register(session, tenant_id, register_id)
        if not register.is_active:
            raise ConflictError(f"register {register.code} is not active")
        # A profile that names its operators is restricted to them: the general ``orders:write``
        # permission is not enough to start a day on it. An ungranted profile stays open to every
        # holder of that permission (``can_operate`` decides, exactly as it did for the old open).
        if (
            register.profile_id is not None
            and actor_user_id is not None
            and not await PosProfileService.can_operate(
                session, tenant_id, register.profile_id, actor_user_id
            )
        ):
            raise ConflictError("this user does not operate this POS profile")
        for _attempt in range(3):
            current = await PosService._today_session(session, tenant_id, register)
            if current is not None:
                return current
            try:
                async with session.begin_nested():
                    fresh = PosSession(
                        tenant_id=tenant_id,
                        register_id=register.id,
                        profile_id=register.profile_id,
                        opened_by_user_id=actor_user_id,
                        status="OPEN",
                        opening_float=opening,
                    )
                    session.add(fresh)
                    await session.flush()
                return fresh
            except IntegrityError:
                continue  # another call opened it first: read theirs
        raise ConflictError("could not start the day for this register")

    @staticmethod
    async def record_sale(
        session: AsyncSession,
        tenant_id: UUID,
        register_id: UUID,
        *,
        items: list[dict] | None,
        customer_id: UUID | None = None,
        discount_total: object = None,
        note: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> dict:
        """RECORD a counter sale: what was sold, at what price, by whom. No payment taken.

        How the customer paid is not this system's business, so there is no tender, no method, no
        amount, no change and no drawer. The order is created (stock reserved), confirmed (the
        reservation becomes a real sale) and a receipt is issued with the seller on it, all in the
        caller's one transaction. It never writes an ``OrderPayment``, a ``Refund`` or a
        ``PosCashMovement``.
        """
        from app.modules.orders.service import OrderService

        register = await PosService._get_register(session, tenant_id, register_id)
        if not register.is_active:
            raise ConflictError(f"register {register.code} is not active")
        if not items:
            raise ValidationError("a sale must contain at least one item")
        seen: set[str] = set()
        for item in items:
            PosService._positive_qty(item.get("quantity"))
            # One line per variant: a later return is valued against that sale line, so the same
            # variant twice (say with two different discounts) would be priced off the first one.
            key = str(item.get("variant_id"))
            if key in seen:
                raise ValidationError("each variant may appear once in a sale: merge its quantity")
            seen.add(key)

        pos_session = await PosService._today_session(session, tenant_id, register)
        if pos_session is None:
            raise ConflictError(
                "the day has not been started: enter the drawer's opening balance first"
            )
        # Queue behind a close (or another sale) of the same day. A close that got here first
        # leaves the day CLOSED, and this sale is refused instead of landing after the balance
        # was already computed.
        pos_session = await PosService._get_session(session, tenant_id, pos_session.id, lock=True)
        if pos_session.status != "OPEN":
            raise ConflictError(
                "the day has been closed: start a new day before recording more sales"
            )
        await PosService._ensure_may_operate(session, tenant_id, pos_session, actor_user_id)
        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        if profile is not None and not profile.is_active:
            raise ConflictError("this POS profile is not active")
        await PosService._ensure_cart_in_scope(session, tenant_id, pos_session, items)
        resolved_customer_id = await PosService._resolve_customer(
            session, tenant_id, profile, customer_id
        )

        order = await OrderService.create_order(
            session,
            tenant_id,
            resolved_customer_id,
            items,
            channel="pos",
            warehouse_id=register.warehouse_id,
            discount_total=discount_total,
            note=note,
        )
        await OrderService.confirm_sale(session, tenant_id, order.id, actor_user_id=actor_user_id)
        receipt = await PosService._issue_receipt(
            session, tenant_id, pos_session, order, sold_by_user_id=actor_user_id
        )
        return {
            "order_id": order.id,
            "order_number": order.number,
            "receipt_id": receipt.id,
            "receipt_number": receipt.number,
            "grand_total": str(order.grand_total),
        }

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
        sold_by_user_id: UUID | None = None,
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
                sold_by_user_id=sold_by_user_id,
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
        closed_by: UUID | None = None,
        shift_override: bool = False,
    ) -> PosSession:
        """OPEN → CLOSED. The day is RECORDED, never counted.

        The close is not a drawer count: nobody types a counted figure and no
        shortage or surplus is computed. What it stores is the day's closing
        balance, derived from the ledgers: opening balance + every invoice
        − every return (an exchange is a return plus a new sale, so its value
        difference is already inside both figures). No payment, drawer
        movement or refund is created here.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        PosService._ensure_holds_shift(pos_session, closed_by, override=shift_override)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, closed_by, override=shift_override
        )
        if pos_session.status != "OPEN":
            raise ConflictError(f"pos session is already {pos_session.status}")
        await PosService._record_close(session, tenant_id, pos_session, closed_by=closed_by)
        return pos_session

    @staticmethod
    async def _record_close(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        *,
        closed_by: UUID | None,
    ) -> None:
        """Compute, store and announce the day's closing balance, then mark it CLOSED.

        The ONE place a day is closed, so a day closed by hand and a day closed automatically
        (a previous day nobody closed) carry the same stored balance and emit the same
        ``pos.session.closed`` event under the same rules.
        """
        from app.core.events.writer import add_outbox_event
        from app.modules.analytics.timekit import merchant_day

        if pos_session.status == "CLOSED":
            # Already closed (a concurrent caller got there first): its balance and its
            # ``pos.session.closed`` event exist. Closing again would announce the day twice.
            return

        closing = (await PosService._day_totals(session, tenant_id, pos_session))["closing_balance"]

        pos_session.status = "CLOSED"
        # Closing balance lives in ``expected_cash`` (an existing column, kept so no table
        # changes); counted/variance stay NULL because nothing is counted any more.
        pos_session.expected_cash = closing
        pos_session.closed_by_user_id = closed_by
        pos_session.closed_at = datetime.now(UTC)
        # A parked cart is a basket, not a sale: it books no money and reserves no stock.
        # Left behind it would be an orphan nobody can resume (a held cart resumes only on its
        # own OPEN session), so the close clears them in the SAME transaction.
        # The shop is told how many before it confirms.
        await session.execute(
            delete(PosHeldCart).where(
                PosHeldCart.tenant_id == tenant_id, PosHeldCart.session_id == pos_session.id
            )
        )
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
                "closing_balance": str(closing),
                # Projection seed figures — the worker RECOMPUTES these from
                # the ledgers (idempotent), the payload rides for consumers
                # that never touch the database.
                # The merchant's calendar day (tenants.timezone), the SAME definition the sales
                # reports and the stale-day rule use. A UTC date drifts a day after 22:00 Cairo.
                "business_date": (
                    merchant_day(
                        pos_session.closed_at, await PosService._shop_timezone(session, tenant_id)
                    ).isoformat()
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

    @staticmethod
    async def _day_totals(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> dict[str, Decimal | int]:
        """Everything that happened in the day, as arithmetic over the ledgers.

        closing balance = opening balance + invoices − returns.
        The POS records, it never settles: no payment method, no tender, no drawer count.
        A return receipt points at the same order as its sale, so sales are counted on
        ``kind == 'sale'`` receipts only and returns on the return lines, never both.
        An exchange is a return receipt plus a new sale receipt (paired by
        ``exchange_return_receipt_id``), so its value difference is already inside both sums;
        it is also reported on its own line.
        """
        from app.modules.orders.models import Order

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
        returns = (
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
        opening = to_money(pos_session.opening_float, "opening_balance")
        sales_total = to_money(sales[1], "sales_total")
        returns_total = to_money(returns[1], "returns_total")
        return {
            "opening_balance": opening,
            "invoice_count": int(sales[0]),
            "sales_total": sales_total,
            "taxes_total": to_money(sales[2], "taxes_total"),
            "return_count": int(returns[0]),
            "returns_total": returns_total,
            "net_sales": sales_total - returns_total,
            "closing_balance": opening + sales_total - returns_total,
        }

    @staticmethod
    async def _day_documents(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> dict[str, list[dict]]:
        """The day's return and exchange invoices, one summary row each."""
        from app.modules.orders.models import Order

        returned = {
            rid: (cnt, total)
            for rid, cnt, total in (
                await session.execute(
                    select(
                        PosReturnLine.receipt_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                        func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                    )
                    .select_from(PosReturnLine)
                    .join(PosReceipt, PosReceipt.id == PosReturnLine.receipt_id)
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReceipt.session_id == pos_session.id,
                    )
                    .group_by(PosReturnLine.receipt_id)
                )
            ).all()
        }
        receipts = (
            (
                await session.execute(
                    select(PosReceipt)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id == pos_session.id,
                    )
                    .order_by(PosReceipt.issued_at.asc(), PosReceipt.id.asc())
                )
            )
            .scalars()
            .all()
        )
        by_id = {r.id: r for r in receipts}
        sale_total = {
            r.id: to_money(total, "total")
            for r, total in (
                await session.execute(
                    select(PosReceipt, Order.grand_total)
                    .join(Order, Order.id == PosReceipt.order_id)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id == pos_session.id,
                        PosReceipt.kind == "sale",
                    )
                )
            ).all()
        }
        exchange_return_ids = {
            r.exchange_return_receipt_id for r in receipts if r.exchange_return_receipt_id
        }
        returns_out: list[dict] = []
        exchanges_out: list[dict] = []
        for r in receipts:
            if r.kind == "return":
                units, total = returned.get(r.id, (0, Decimal("0")))
                row = {
                    "receipt_id": str(r.id),
                    "receipt_number": r.number,
                    "issued_at": r.issued_at.isoformat(),
                    "units": int(units),
                    "total": str(to_money(total, "total")),
                }
                if r.id in exchange_return_ids:
                    new_sale = next(
                        (x for x in receipts if x.exchange_return_receipt_id == r.id), None
                    )
                    new_total = (
                        sale_total.get(new_sale.id, Decimal("0")) if new_sale else Decimal("0")
                    )
                    row["new_receipt_number"] = new_sale.number if new_sale else None
                    row["new_total"] = str(new_total)
                    row["difference"] = str(new_total - to_money(total, "total"))
                    exchanges_out.append(row)
                else:
                    returns_out.append(row)
        _ = by_id
        return {"returns": returns_out, "exchanges": exchanges_out}

    # ------------------------------------------------------- close preview ----

    @staticmethod
    async def close_preview(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """What the close will record: the day's figures and the closing balance. Read-only."""
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        totals = await PosService._day_totals(session, tenant_id, pos_session)
        return {
            "session_id": pos_session.id,
            "status": pos_session.status,
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in totals.items()},
        }

    # ------------------------------------------------------------- lookup ----

    @staticmethod
    async def list_sessions(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        register_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PosSession]:
        """Resume the till: the sessions behind this drawer, newest first. ``limit`` is the
        caller's page size (the export asks for 500); it is never silently cut below that.
        ``offset`` skips that many newer rows, so a long history can be read page by page."""
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
                    query.order_by(PosSession.opened_at.desc(), PosSession.id.desc())
                    .limit(limit)
                    .offset(max(0, offset))
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def get_receipt(session: AsyncSession, tenant_id: UUID, receipt_id: UUID) -> dict:
        """The printed artifact: receipt header + order lines (+ payments an OLD sale recorded).

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
                    # The line's own discount: a client prices a return the way the server does
                    # (the customer paid gross minus THIS, not a share of the basket discount).
                    "discount_pct": str(
                        Decimal(str(line.discount_pct or 0)).quantize(Decimal("0.01"))
                    ),
                    "total": str(line.total),
                    "returned_qty": int(returned_by_variant.get(line.variant_id, 0)),
                }
                for line in lines
            ]
        fully_returned = bool(lines) and all(
            int(returned_by_variant.get(item.variant_id, 0)) >= item.quantity for item in lines
        )
        return {
            "receipt": {
                "id": receipt.id,
                "number": receipt.number,
                "kind": receipt.kind,
                "exchange_return_receipt_id": receipt.exchange_return_receipt_id,
                "sold_by_user_id": (
                    str(receipt.sold_by_user_id) if receipt.sold_by_user_id else None
                ),
                "issued_at": receipt.issued_at.isoformat(),
                "tendered_amount": (
                    str(receipt.tendered_amount) if receipt.tendered_amount is not None else None
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
                "note": (order.extra or {}).get("note") if order else None,
                "fully_returned": fully_returned if receipt.kind == "sale" else None,
            },
            "lines": lines_payload,
            "tenders": [
                {"method": t.method, "amount": str(t.amount), "status": t.status} for t in tenders
            ],
        }

    @staticmethod
    async def list_receipts(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> list[dict]:
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
        from app.core.sql import arabic_regex

        rows = (
            (
                await session.execute(
                    select(PosReceipt)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.kind == "sale",
                        # Arabic-Indic digits and a missing dash still find the receipt.
                        PosReceipt.number.op("~*")(arabic_regex(term)),
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
        """The day's report: opening balance, invoices, returns, exchanges, closing balance.

        Live while the day is OPEN, the same arithmetic after it CLOSES: it is computed from the
        ledgers every time, never remembered, and it carries no counted figure and no variance.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        totals = await PosService._day_totals(session, tenant_id, pos_session)
        docs = await PosService._day_documents(session, tenant_id, pos_session)
        exchange_diff = sum((Decimal(x["difference"]) for x in docs["exchanges"]), Decimal("0"))
        return {
            "session": {
                "id": str(pos_session.id),
                "register_id": str(pos_session.register_id),
                "profile_id": (str(pos_session.profile_id) if pos_session.profile_id else None),
                "cashier_user_id": (
                    str(pos_session.cashier_user_id) if pos_session.cashier_user_id else None
                ),
                "status": pos_session.status,
                "opened_at": pos_session.opened_at.isoformat(),
                "closed_at": (pos_session.closed_at.isoformat() if pos_session.closed_at else None),
            },
            "opening_balance": str(totals["opening_balance"]),
            "sales": {
                "invoice_count": totals["invoice_count"],
                "total": str(totals["sales_total"]),
            },
            "returns": {
                "return_count": totals["return_count"],
                "total": str(totals["returns_total"]),
                "documents": docs["returns"],
            },
            "exchanges": {
                "exchange_count": len(docs["exchanges"]),
                "difference_total": str(to_money(exchange_diff, "exchange_difference")),
                "documents": docs["exchanges"],
            },
            "net_sales": str(totals["net_sales"]),
            "closing_balance": str(totals["closing_balance"]),
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
        from app.modules.analytics.timekit import resolve_timezone
        from app.modules.orders.models import Order

        shop_tz = resolve_timezone(await PosService._shop_timezone(session, tenant_id))
        day_sessions = (
            (
                await session.execute(
                    select(PosSession).where(
                        PosSession.tenant_id == tenant_id,
                        PosSession.status == "CLOSED",
                        # The business date is the MERCHANT's calendar day, spelled out with the
                        # shop's zone (never a bare func.date(), which would use the database
                        # SESSION's zone) so it agrees with the date the close event carries.
                        func.date(func.timezone(shop_tz, PosSession.closed_at)) == business_date,
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
                    # Nothing is counted any more: old columns stay (history kept), zero/empty.
                    variance_total=Decimal("0"),
                    by_method=[],
                )
            )
            written += 1
        await session.flush()
        return written

    @staticmethod
    async def top_products(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        since: date,
        until: date,
        limit: int = 20,
    ) -> list[dict]:
        """Best sellers over ``[since, until]`` (shop days, inclusive), ranked by net revenue.

        Per variant, straight from the order lines of ``sale`` receipts: quantity and revenue (the
        line's NET after the cashier's discount), minus what was RETURNED in the same window, so a
        product that sells and comes back does not rank as a hit. There is deliberately no cost or
        profit here: an order line does not record the cost at the time of sale, and a profit
        computed from today's average cost would be a guess presented as a fact.
        """
        from zoneinfo import ZoneInfo

        from app.modules.orders.models import Order, OrderItem
        from app.modules.pos.stock_view import StockViewService

        tz = (await PosService._shop_timezone(session, tenant_id) or "UTC").strip() or "UTC"
        zone = ZoneInfo(tz)
        lo = datetime(since.year, since.month, since.day, tzinfo=zone).astimezone(UTC)
        nxt = until + timedelta(days=1)
        hi = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone).astimezone(UTC)

        # Each sale's lines carry their own NET (after the cashier's line discount) but NOT the
        # invoice-level discount, which lives on the order. Share it out over the lines in
        # proportion to their net, rounded per line HALF_UP: the rule `_return_line_totals` refunds
        # with, so a product's revenue here and its refund there are the same number.
        lines = (
            await session.execute(
                select(
                    PosReceipt.order_id,
                    Order.grand_total,
                    OrderItem.id,
                    OrderItem.variant_id,
                    OrderItem.quantity,
                    OrderItem.total,
                )
                .select_from(PosReceipt)
                .join(Order, Order.id == PosReceipt.order_id)
                .join(OrderItem, OrderItem.order_id == PosReceipt.order_id)
                .where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.kind == "sale",
                    PosReceipt.issued_at >= lo,
                    PosReceipt.issued_at < hi,
                )
                .order_by(PosReceipt.order_id, OrderItem.id)
            )
        ).all()
        by_order: dict = {}
        for order_id, grand, _item_id, variant_id, qty, total in lines:
            by_order.setdefault(order_id, (to_money(grand, "grand"), []))[1].append(
                (variant_id, int(qty), to_money(total, "total"))
            )
        money = Decimal("0.01")
        totals_by_variant: dict = {}
        for grand, items in by_order.values():
            net_base = sum((t for _v, _q, t in items), Decimal("0"))
            allocated = Decimal("0")
            shares = []
            for _v, _q, t in items:
                share = (
                    (grand * t / net_base).quantize(money, rounding=ROUND_HALF_UP)
                    if net_base > 0
                    else t
                )
                shares.append(share)
                allocated += share
            # rounding can leave a cent or two: give it to the largest line so a sale always adds up
            if shares and allocated != grand and net_base > 0:
                biggest = max(range(len(items)), key=lambda i: items[i][2])
                shares[biggest] += grand - allocated
            for (variant_id, qty, _t), share in zip(items, shares, strict=True):
                q0, r0 = totals_by_variant.get(variant_id, (0, Decimal("0")))
                totals_by_variant[variant_id] = (q0 + qty, r0 + share)
        sold = [(vid, q, r) for vid, (q, r) in totals_by_variant.items()]
        returned = {
            variant_id: (int(qty), to_money(amount, "returned"))
            for variant_id, qty, amount in (
                await session.execute(
                    select(
                        PosReturnLine.variant_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                        func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                    )
                    .select_from(PosReturnLine)
                    .join(PosReceipt, PosReceipt.id == PosReturnLine.receipt_id)
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReceipt.issued_at >= lo,
                        PosReceipt.issued_at < hi,
                    )
                    .group_by(PosReturnLine.variant_id)
                )
            ).all()
        }
        ranked = []
        for variant_id, qty, revenue in sold:
            r_qty, r_amount = returned.get(variant_id, (0, Decimal("0")))
            net_qty = int(qty) - r_qty
            net_revenue = to_money(revenue, "revenue") - r_amount
            ranked.append((variant_id, int(qty), r_qty, net_qty, net_revenue))
        ranked.sort(key=lambda t: (t[4], t[3]), reverse=True)
        ranked = ranked[: max(1, min(limit, 100))]
        names = await StockViewService.names_for(session, tenant_id, [t[0] for t in ranked])
        out = []
        for variant_id, qty, r_qty, net_qty, net_revenue in ranked:
            title, sku = names.get(variant_id, (None, None))
            out.append(
                {
                    "variant_id": str(variant_id),
                    "product_title": title,
                    "sku": sku,
                    "sold_qty": qty,
                    "returned_qty": r_qty,
                    "net_qty": net_qty,
                    "net_revenue": str(to_money(net_revenue, "net_revenue")),
                }
            )
        return out

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
            (await session.execute(query.order_by(PosDailySales.register_id.asc()))).scalars().all()
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
        actor_user_id: UUID | None = None,
        override: bool = False,
    ) -> PosHeldCart:
        """Park a basket on the OPEN session; reserve nothing, book nothing.

        A hold is a convenience for the cashier, not a sale: it validates the
        lines are shaped right (a variant id and a positive quantity) so a
        parked cart cannot rot into an unsellable one, but it deliberately does
        NOT price them, reserve them, or touch money. The price is struck at
        sell time from the tenant's ladder; a hold therefore never freezes a
        price the catalog may since have changed.
        """
        # The day's row is taken FOR UPDATE, like a sale: a close queues behind this hold (and
        # clears the cart with the rest), or this hold queues behind the close and finds the day
        # CLOSED. Without the lock a cart could be parked on a day that has just been closed.
        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=override
        )
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
                to_money(discount_total, "discount_total") if discount_total is not None else None
            ),
            label=(str(label).strip() or None) if label is not None else None,
            held_by_user_id=held_by,
        )
        session.add(held)
        await session.flush()
        return held

    @staticmethod
    async def list_held_carts(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        actor_user_id: UUID | None = None,
        override: bool = False,
    ) -> list[PosHeldCart]:
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=override
        )
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
        session: AsyncSession,
        tenant_id: UUID,
        held_cart_id: UUID,
        *,
        actor_user_id: UUID | None = None,
        override: bool = False,
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
        # A cart belongs to a day; whoever may not use that day's till may not read its carts.
        owning_day = await PosService._get_session(session, tenant_id, held.session_id)
        await PosService._ensure_may_operate(
            session, tenant_id, owning_day, actor_user_id, override=override
        )
        return held

    @staticmethod
    async def release_held_cart(
        session: AsyncSession,
        tenant_id: UUID,
        held_cart_id: UUID,
        *,
        actor_user_id: UUID | None = None,
        override: bool = False,
    ) -> None:
        """Drop a parked cart — the customer left, or it became a sale."""
        held = await PosService.get_held_cart(
            session, tenant_id, held_cart_id, actor_user_id=actor_user_id, override=override
        )
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
                actor_user_id=actor_user_id,
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
    async def _cap_to_unreturned_value(
        session: AsyncSession,
        tenant_id: UUID,
        order: object,
        sold: dict,
        requested: dict,
        priced: list[Decimal],
        sold_net: Decimal,
    ) -> list[Decimal]:
        """Never refund more than the invoice value that has not already come back.

        A weighted-average unit price is rounded to cents, and that rounding can push the sum of
        a variant's returns above what it was sold for (2 units at 10.00 and 10.01 average
        10.005, so returning both would book 20.02 against a 20.01 invoice). The variant's whole
        value is what returning ALL of its sold units is worth (priced once, in one step, with the
        order discount applied, and never above its lines' exact net); a return never exceeds that
        minus what earlier returns booked, and the return that takes the LAST units takes exactly
        what is left, so every return on the invoice adds up to its value to the cent.
        """
        variants = list(sold)
        whole = PosService._return_line_totals(
            Decimal(str(order.subtotal)),
            Decimal(str(order.discount_total)),
            [(sold[v]["unit_price"], sold[v]["quantity"], sold[v]["line_pct"]) for v in variants],
            sold_net_subtotal=sold_net,
        )
        value = {
            v: min(w, Decimal(str(sold[v]["line_net"]))) if sold[v]["line_net"] else w
            for v, w in zip(variants, whole, strict=True)
        }
        booked: dict = {}
        returned_qty: dict = {}
        for variant_id, qty, amount in (
            await session.execute(
                select(
                    PosReturnLine.variant_id,
                    func.coalesce(func.sum(PosReturnLine.quantity), 0),
                    func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                )
                .where(
                    PosReturnLine.tenant_id == tenant_id,
                    PosReturnLine.order_id == order.id,
                )
                .group_by(PosReturnLine.variant_id)
            )
        ).all():
            returned_qty[variant_id] = int(qty)
            booked[variant_id] = Decimal(str(amount))
        capped: list[Decimal] = []
        for variant_id, amount in zip(requested, priced, strict=True):
            left = max(Decimal("0"), value[variant_id] - booked.get(variant_id, Decimal("0")))
            remaining_qty = sold[variant_id]["quantity"] - returned_qty.get(variant_id, 0)
            if requested[variant_id] >= remaining_qty:
                amount = left  # the last units take exactly what is left
            capped.append(to_money(min(amount, left), "refund_total"))

        # The invoice as a whole: an order discount shared across lines rounds line by line (three
        # 10.00 lines under a 0.01 discount each carry a share of 0.0033, i.e. 0.00), so the lines
        # can add up to more than the invoice was worth. Every return together stays within the
        # invoice total; the return that takes the last units takes exactly what is left, and any
        # excess comes off the last line being returned.
        invoice_total = Decimal(str(order.grand_total))
        already = sum(booked.values(), Decimal("0"))
        left_on_invoice = max(Decimal("0"), invoice_total - already)
        takes_everything = all(
            sold[v]["quantity"] - returned_qty.get(v, 0) <= requested.get(v, 0) for v in sold
        )
        wanted = sum(capped, Decimal("0"))
        target = left_on_invoice if takes_everything else min(wanted, left_on_invoice)
        excess = wanted - target
        for i in range(len(capped) - 1, -1, -1):
            if excess <= 0:
                break
            cut = min(capped[i], excess)
            capped[i] = to_money(capped[i] - cut, "refund_total")
            excess -= cut
        return capped

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
    ) -> dict:
        """Record the goods coming back, line by line. No money moves.

        The return is a document against the original sale: each line is
        capped at sold-minus-already-returned and valued at the ORIGINAL line's
        unit price minus its discount share. The value is recorded on the
        return receipt; nothing is refunded or paid out. ``restock`` also puts the returned
        quantities back on the register's shelf. A return receipt (``POS-RET-``) is issued and the
        returned lines are recorded on it, which is what every later return
        caps against.
        """
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.models import InventoryMovement
        from app.modules.inventory.service import InventoryService
        from app.modules.orders.models import Order, OrderItem

        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=shift_override
        )
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
        # The sale may have been rung on an EARLIER shift, even one whose day is already closed: the
        # customer comes back tomorrow. Quantities and prices are checked against the ORIGINAL sale
        # (below); the return itself is recorded on the day that is open NOW. Booking it on the old
        # day would change a closed report after the fact.

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
        # both pass and the shelf grows twice for one unit. The row lock makes the second one wait,
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
                item.variant_id,
                {
                    "quantity": 0,
                    "unit_price": None,
                    "line_pct": Decimal("0"),
                    "gross": Decimal("0"),
                    "line_net": Decimal("0"),
                    "pct_weight": Decimal("0"),
                },
            )
            entry["quantity"] += item.quantity
            # Every line the variant sold on counts, weighted by its quantity: the same variant
            # can sit on one invoice at two prices, and the first line alone is not "the price".
            line_gross = to_money(item.unit_price, "unit_price") * item.quantity
            entry["gross"] += line_gross
            entry["line_net"] += Decimal(str(item.total))
            entry["pct_weight"] += line_gross * Decimal(str(item.discount_pct or 0))
            sold_net += Decimal(str(item.total))

        for entry in sold.values():
            if entry["quantity"]:
                entry["unit_price"] = to_money(entry["gross"] / entry["quantity"], "unit_price")
            if entry["gross"]:
                entry["line_pct"] = entry["pct_weight"] / entry["gross"]

        unknown = set(requested) - set(sold)
        if unknown:
            raise ValidationError(
                f"{len(unknown)} returned variant(s) were never sold on this order"
            )

        # The quantity cap: a variant cannot come back more times than it sold.
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
            # The shelf cap, separate from the quantity cap: a return that did not restock put
            # nothing back on the shelf, and goods already back cannot come back twice.
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
                goods_cap = sold[variant_id]["quantity"] - int(restocked_already.get(variant_id, 0))
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
        priced = await PosService._cap_to_unreturned_value(
            session, tenant_id, order, sold, requested, priced, sold_net
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
        # The cashier layer does not move money: a return records the goods and the invoice value
        # only. Old sales that took payments keep them untouched (history is kept), but a return
        # never creates a Refund, an OrderPayment or a drawer movement.

        restocked = False
        if restock:
            register = await PosService._get_register(session, tenant_id, pos_session.register_id)
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
                    actor_user_id=actor_user_id,
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
                "restocked": restocked,
            },
            producer="pos",
        )
        return {
            "receipt_id": return_receipt.id,
            "receipt_number": return_receipt.number,
            "refunded_total": str(refund_total),
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
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> dict:
        """The one-transaction exchange: record the returned goods and the replacement sale.

        Nothing is paid, refunded or put in a drawer. The return is a document against the
        original sale (capped at sold-minus-already-returned, priced at the original line price),
        the replacement is a new order priced off the CURRENT ladder, and the value difference is
        only reported. Both commit together under two receipts, paired by the return receipt id.
        The exchange keeps the original order's customer."""
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.models import InventoryMovement
        from app.modules.inventory.service import InventoryService
        from app.modules.orders.models import Order, OrderItem
        from app.modules.orders.service import OrderService

        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=shift_override
        )
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
        # checked against that sale; the exchange is recorded on the day that is open now.

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
        # both pass and the shelf grows twice for one unit. The row lock makes the second one wait,
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
                item.variant_id,
                {
                    "quantity": 0,
                    "unit_price": None,
                    "line_pct": Decimal("0"),
                    "gross": Decimal("0"),
                    "line_net": Decimal("0"),
                    "pct_weight": Decimal("0"),
                },
            )
            entry["quantity"] += item.quantity
            # Every line the variant sold on counts, weighted by its quantity: the same variant
            # can sit on one invoice at two prices, and the first line alone is not "the price".
            line_gross = to_money(item.unit_price, "unit_price") * item.quantity
            entry["gross"] += line_gross
            entry["line_net"] += Decimal(str(item.total))
            entry["pct_weight"] += line_gross * Decimal(str(item.discount_pct or 0))
            sold_net += Decimal(str(item.total))

        for entry in sold.values():
            if entry["quantity"]:
                entry["unit_price"] = to_money(entry["gross"] / entry["quantity"], "unit_price")
            if entry["gross"]:
                entry["line_pct"] = entry["pct_weight"] / entry["gross"]

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
                goods_cap = sold[variant_id]["quantity"] - int(restocked_already.get(variant_id, 0))
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
        priced = await PosService._cap_to_unreturned_value(
            session, tenant_id, order, sold, requested, priced, sold_net
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

        # The cashier layer does not move money: an exchange records the goods and both invoice
        # values; the difference is only reported, never refunded, charged or put in a drawer. Old
        # sales that took payments keep them untouched (history is kept).
        profile = await PosService.resolve_profile(session, tenant_id, pos_session)  # noqa: F841

        # ---------- commit: order, payments, receipts ------------------------
        register = await PosService._get_register(session, tenant_id, pos_session.register_id)
        new_order = await OrderService.create_order(
            session,
            tenant_id,
            order.customer_id,  # the exchange keeps the original customer
            new_lines,
            channel="pos",
            warehouse_id=register.warehouse_id,
        )
        await OrderService.confirm_sale(
            session, tenant_id, new_order.id, actor_user_id=actor_user_id
        )

        if restock:
            for entry in return_entries:
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
                    actor_user_id=actor_user_id,
                )

        return_receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            number_prefix="POS-RET",
            kind="return",
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
            session,
            tenant_id,
            pos_session,
            new_order,
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
            "restocked": restock,
        }
