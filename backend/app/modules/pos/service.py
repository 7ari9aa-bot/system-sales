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

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import case, delete, func, or_, select
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
from app.modules.pos.profiles import PAYMENT_METHODS, PosProfileService
from app.modules.pos.receipt_reads import PosReceiptReads
from app.modules.pos.refund import (
    REFUND_COUNTED_STATES,
    REFUNDABLE_PAYMENT_STATES,
    Tender,
    plan_for,
)
from app.modules.pos.tender import (
    CASH,
    check_close_variance,
    expected_drawer_cash,
    parse_lines,
    settle,
    variance,
)

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


class PosService(PosReceiptReads):
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
            # What the cashier is about to do: record the money, or only the sale. The header says
            # it out loud, so nobody discovers after the customer has gone that no payment was
            # taken. ``reason`` explains a record-only till the shop did not choose.
            "payments_mode": await PosService.payments_mode(session, tenant_id, pos_session),
        }

    @staticmethod
    async def payments_mode(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> dict:
        """``record`` (the till takes payments) or ``record_only`` (it does not), and why."""
        takes = bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        )
        if takes:
            return {"mode": "record", "reason": None, "apparel_setup_incomplete": False}
        from app.core.activity_setup import NOT_STARTED, SKIPPED, read_state
        from app.modules.settings.service import SettingsService

        setup_state = await read_state(session, tenant_id)
        vertical = str(await SettingsService(session, tenant_id).value("business.vertical") or "")
        incomplete = vertical == "apparel" and setup_state in {NOT_STARTED, SKIPPED}
        return {
            "mode": "record_only",
            "reason": (
                "the apparel setup was skipped, so no payment method is recorded"
                if incomplete
                else "pos.take_payments is off"
            ),
            "apparel_setup_incomplete": incomplete,
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

    @staticmethod
    async def add_cash_movement(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        direction: str,
        reason: str,
        amount: object,
        notes: str | None = None,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> PosCashMovement:
        """Record a manual drawer movement (pay-in, pay-out, cash drop).

        NOT for sales or refunds — those are recorded by the sell/return flows.
        Locks the session row to prevent race with close. Like every other money operation on a
        drawer it belongs to the cashier who holds it (or a manager with ``pos:override``): a
        pay-out is the one way to take cash out of a drawer without a sale, so it cannot be open
        to anybody who knows the session id.
        """
        _MANUAL_REASONS = {"pay_in", "pay_out", "cash_drop"}
        if reason not in _MANUAL_REASONS:
            raise ValidationError(f"reason must be one of {sorted(_MANUAL_REASONS)}")
        if direction not in {"in", "out"}:
            raise ValidationError("direction must be 'in' or 'out'")
        expected_dir = "in" if reason == "pay_in" else "out"
        if direction != expected_dir:
            raise ValidationError(f"reason '{reason}' requires direction '{expected_dir}'")

        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        if pos_session.status != "OPEN":
            raise ConflictError("cannot add cash movement to a closed session")
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=shift_override
        )

        amt = _positive_amount(amount, "amount")
        movement = PosCashMovement(
            tenant_id=tenant_id,
            session_id=session_id,
            direction=direction,
            reason=reason,
            amount=amt,
            notes=str(notes).strip()[:255] if notes else None,
            created_by_user_id=actor_user_id,
        )
        session.add(movement)
        await session.flush()
        return movement

    @staticmethod
    async def list_cash_movements(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> list[PosCashMovement]:
        rows = (
            (
                await session.execute(
                    select(PosCashMovement)
                    .where(
                        PosCashMovement.tenant_id == tenant_id,
                        PosCashMovement.session_id == session_id,
                    )
                    .order_by(PosCashMovement.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

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
    def _gs1_check_digit(body: str) -> int:
        """The GS1 check digit for ``body`` (the code without its last digit).

        From the right, digits are weighted 3, 1, 3, 1...; the check digit tops the sum up to the
        next multiple of ten. The same rule covers EAN-8, UPC-A (12), EAN-13 and GTIN-14.
        """
        total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
        return (10 - total % 10) % 10

    @staticmethod
    def _clean_scanned_code(value: str) -> str:
        """What a scanner or a keyboard really meant, before the code is looked up or judged.

        Arabic-Indic and full-width digits become plain digits (an Arabic keyboard types them),
        a leading AIM symbology prefix (``]E0``, ``]C1``...) that some scanners add is dropped,
        and invisible characters (zero-width, control) are removed. Anything else is left exactly
        as it was: a SKU or a free-text code must still match what the shop registered.
        """
        import unicodedata

        out: list[str] = []
        for ch in value:
            if unicodedata.category(ch) in ("Cc", "Cf"):
                continue
            digit = unicodedata.digit(ch, None)
            out.append(str(digit) if digit is not None and ch.isdigit() else ch)
        code = "".join(out).strip()
        if len(code) > 3 and code[0] == "]" and code[1].isalpha() and code[2].isalnum():
            code = code[3:]
        return code

    @staticmethod
    def _zero_padded_forms(code: str) -> list[str]:
        """The same product's other GS1 spellings: UPC-A (12), EAN-13 and GTIN-14 differ only by
        leading zeros, and a scanner may report either. Only plain digits of a barcode length."""
        if not (code.isascii() and code.isdigit()) or len(code) not in (8, 12, 13, 14):
            return []
        bare = code.lstrip("0")
        forms = []
        for width in (12, 13, 14):
            padded = bare.zfill(width)
            if padded != code and len(bare) <= width:
                forms.append(padded)
        return forms

    @staticmethod
    def _is_misread_barcode(value: str) -> bool:
        """True for a code shaped like a packaged barcode whose check digit does not add up.

        Only 8, 12, 13 or 14 plain digits can be a GS1 barcode. Anything else (a SKU, a short
        internal number, text) is not judged: it is just an unknown code.
        """
        code = value.strip()
        if len(code) not in (8, 12, 13, 14) or not (code.isascii() and code.isdigit()):
            return False
        return PosService._gs1_check_digit(code[:-1]) != int(code[-1])

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

        # A hand scanner reads a code, not its type: the till sends ``barcode`` for everything.
        # But a packaged product is registered as ``ean``/``gtin``/``upc``, so an exact-type lookup
        # alone missed most real codes and the till fell back to a substring search that can match
        # two items. A generic ``barcode`` scan therefore tries the other scannable types too, in
        # the same order the stock list shows them. A specific type stays exact (it never widens).
        types = [identifier_type]
        if identifier_type == "barcode":
            types += ["ean", "gtin", "upc"]
        # A generic scan is cleaned first (Arabic digits, scanner prefix, invisible characters). A
        # named type stays exactly what was sent: it never widens.
        if identifier_type == "barcode":
            value = PosService._clean_scanned_code(value)
        spellings = [value]
        if identifier_type == "barcode":
            spellings += PosService._zero_padded_forms(value)
        variant = None
        for spelling in spellings:
            for candidate in types:
                variant = await CatalogService.resolve_identifier(
                    session, tenant_id, candidate, spelling
                )
                if variant is not None:
                    break
            if variant is not None:
                break
        if variant is None:
            # Looked up FIRST on purpose: a shop may have registered an old or internal number of
            # barcode length, and that must still sell. Only a code that is nowhere in the shop AND
            # fails its check digit is called a misread. A hand scanner (the generic ``barcode``
            # scan) is where misreads happen; a caller that names a type gets the exact lookup.
            if identifier_type == "barcode" and PosService._is_misread_barcode(value):
                return {"found": False, "refusal": "invalid_barcode"}
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
            "title": line_title(
                product.title if product else None, variant.title, variant.option_values
            ),
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
                    "title": line_title(product_title, variant.title, variant.option_values),
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
        discount into one discount_total — unless the shop owner set a discount
        ceiling on the profile, in which case a discount above it is refused (a manager is exempt).
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
        await PosService._ensure_within_discount_ceiling(
            session,
            tenant_id,
            await PosService.resolve_profile(session, tenant_id, pos_session),
            items,
            discount_total,
            override=override,
        )
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
    async def _setting(
        session: AsyncSession, tenant_id: UUID, key: str, pos_session: PosSession
    ) -> object:
        """The effective value of ``key`` for the till this shift ran on.

        Resolved down the shop's hierarchy from the shift's profile, so a branch or a single till
        can differ from the shop. A shift with no profile reads the shop-wide value.
        """
        from app.modules.settings.service import SettingsService

        svc = SettingsService(session, tenant_id)
        if pos_session.profile_id is None:
            return await svc.value(key)
        return await svc.value(key, scope="pos_profile", scope_id=pos_session.profile_id)

    @staticmethod
    async def tender_rules(session: AsyncSession, tenant_id: UUID, pos_session: PosSession) -> dict:
        """How this till may take money, for the screen to start from.

        The same settings and profile ``record_sale`` enforces, so the screen and the server cannot
        disagree: a till that records payments refuses a sale with no payment line, and a sale on
        account needs BOTH ``pos.take_payments`` and ``pos.allow_sale_on_account``.
        """
        take = bool(await PosService._setting(session, tenant_id, "pos.take_payments", pos_session))
        on_account = take and bool(
            await PosService._setting(session, tenant_id, "pos.allow_sale_on_account", pos_session)
        )
        profile = (
            await PosProfileService.get(session, tenant_id, pos_session.profile_id)
            if pos_session.profile_id is not None
            else None
        )
        methods = list(profile.allowed_payment_methods or []) if profile is not None else ["cash"]
        required = await PosService._setting(
            session, tenant_id, "pos.reference_required_methods", pos_session
        )
        return {
            "take_payments": take,
            "allow_on_account": on_account,
            "methods": methods if take else [],
            "reference_required": [str(m) for m in (required or [])] if take else [],
        }

    @staticmethod
    async def return_policy(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """What this till's owner decided about returns, for the cashier screen to start from.

        The same three answers the return and exchange paths read themselves, resolved for this
        shift's till, so the screen's starting point can never disagree with what the server does.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        get = lambda key: PosService._setting(session, tenant_id, key, pos_session)  # noqa: E731
        return_days = await get("pos.return_max_days")
        exchange_days = await get("pos.exchange_max_days")
        return {
            "restock_default": bool(await get("pos.return_restock_default")),
            "reasons": [str(r) for r in (await get("pos.return_reasons") or [])],
            "return_max_days": None if return_days is None else int(return_days),
            # 0 means "same as returns", resolved here so the screen never has to know that rule.
            "exchange_max_days": (
                None
                if return_days is None and not exchange_days
                else int(exchange_days or return_days)
            ),
        }

    @staticmethod
    async def _resolve_restock(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        restock: bool | None,
    ) -> bool:
        """The cashier's choice when given, else the shop's ``pos.return_restock_default``."""
        if restock is not None:
            return bool(restock)
        return bool(
            await PosService._setting(session, tenant_id, "pos.return_restock_default", pos_session)
        )

    @staticmethod
    def _line_restock(lines: list[dict], restock: bool) -> dict[UUID, bool]:
        """Which returned variants go back on the shelf: the line's own choice, else ``restock``.

        ``restock`` is the request-wide answer (already resolved against the shop's default). A
        line may override it for its own piece. Two lines for one variant are merged into one
        quantity later, so they must agree: refusing is better than guessing which one wins.
        """
        decided: dict[UUID, bool] = {}
        for line in lines:
            variant_id = UUID(str(line["variant_id"]))
            own = line.get("restock")
            choice = restock if own is None else bool(own)
            if variant_id in decided and decided[variant_id] != choice:
                raise ValidationError(
                    f"variant {variant_id} is on two return lines with different shelf decisions"
                )
            decided[variant_id] = choice
        return decided

    @staticmethod
    async def _clean_return_reasons(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        lines: list[dict],
    ) -> dict[UUID, str | None]:
        """Each line's reason, checked against the owner's ``pos.return_reasons`` list.

        A reason is optional. One that is not on the list is refused: the list is how the owner
        keeps the reports readable ("size" and "Size " would be two different bars).
        """
        allowed = await PosService._setting(session, tenant_id, "pos.return_reasons", pos_session)
        allowed_set = {str(r) for r in (allowed or [])}
        reasons: dict[UUID, str | None] = {}
        for line in lines:
            raw = line.get("reason")
            reason = str(raw).strip() if raw is not None else ""
            if reason and reason not in allowed_set:
                raise ValidationError(
                    f"return reason {reason!r} is not one of this shop's reasons "
                    f"{sorted(allowed_set)} (pos.return_reasons)"
                )
            reasons[UUID(str(line["variant_id"]))] = reason or None
        return reasons

    @staticmethod
    async def _ensure_within_window(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        issued_at: datetime,
        *,
        key: str,
        fallback_key: str | None = None,
        what: str,
    ) -> None:
        """Refuse when the sale is older than the shop's window. ``0`` on ``key`` means "use
        ``fallback_key``"; a ``None`` window means no limit."""
        window = await PosService._setting(session, tenant_id, key, pos_session)
        if fallback_key is not None and (window is None or int(window) == 0):
            window = await PosService._setting(session, tenant_id, fallback_key, pos_session)
        if window is not None and (datetime.now(UTC) - issued_at).days > int(window):
            raise ConflictError(f"this sale is past the {int(window)}-day {what} window ({key})")

    @staticmethod
    async def _discount_ceiling(
        session: AsyncSession, tenant_id: UUID, profile: PosProfile | None
    ) -> Decimal | None:
        """The ceiling in force for this till, or None for no ceiling.

        The profile's own ``max_discount_pct`` is the most specific answer and wins when set, so
        every ceiling a shop already has keeps meaning exactly what it meant. Only when the
        profile has none does the setting ``pos.max_discount_pct`` apply, resolved down the
        shop's hierarchy (tenant, branch, the profile's warehouse, the profile), so an owner can
        set one rule for the whole shop or one branch without editing every till.
        """
        if profile is None:
            return None
        if profile.max_discount_pct is not None:
            return Decimal(profile.max_discount_pct)
        from app.modules.settings.service import SettingsService

        resolved = await SettingsService(session, tenant_id).value(
            "pos.max_discount_pct", scope="pos_profile", scope_id=profile.id
        )
        return None if resolved is None else Decimal(str(resolved))

    @staticmethod
    async def _ensure_within_discount_ceiling(
        session: AsyncSession,
        tenant_id: UUID,
        profile: PosProfile | None,
        items: list[dict],
        discount_total: object,
        *,
        override: bool,
    ) -> None:
        """The shop owner's discount ceiling (``pos_profiles.max_discount_pct``).

        Measures the discount that really applies, the typed invoice discount PLUS every line
        percentage, as a share of the sale before any discount. Looking at one field alone would
        let a cashier split a discount across the two. No ceiling set (NULL), a till with no
        profile with no settings above it, or a manager (``pos:override``) means no check.
        """
        if override:
            return
        ceiling = await PosService._discount_ceiling(session, tenant_id, profile)
        if ceiling is None:
            return
        subtotal, _lines, line_discounts = await PosService._price_lines(session, tenant_id, items)
        if subtotal <= 0:
            return
        applied = to_money(discount_total or 0, "discount_total") + line_discounts
        if applied * Decimal("100") > subtotal * Decimal(ceiling):
            raise ValidationError(
                f"this discount is above the {ceiling:f}% this shop allows; "
                "ask a manager or lower the discount"
            )

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
                        # The day has a holder: without it ``_ensure_holds_shift`` treats the
                        # drawer as nobody's and any ``orders:write`` user could close it or
                        # return against it. ``pos:override`` (a manager) still covers for it.
                        cashier_user_id=actor_user_id,
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
    async def _check_prescription(
        session: AsyncSession, tenant_id: UUID, items: list[dict], reference: dict | None
    ) -> dict[str, str] | None:
        """Refuse a prescription-only product sold without a named prescription.

        The workspace's answer decides (the vertical sets the default), so a shop without the
        capability is never refused and an ordinary cart never costs more than the two reads.
        """
        from app.modules.catalog.service import CatalogService
        from app.modules.pos.prescription import ensure_prescription_given
        from app.modules.settings.capabilities import shop_capabilities

        wanted: set[UUID] = set()
        for item in items:
            try:
                wanted.add(UUID(str(item["variant_id"])))
            except (KeyError, ValueError):
                continue  # the pricing step reports a malformed id with the proper message
        products: list = []
        if wanted:
            variants = await CatalogService.get_variants_by_ids(session, tenant_id, wanted)
            found = await CatalogService.get_products_by_ids(
                session, tenant_id, sorted({v.product_id for v in variants.values()})
            )
            products = list(found.values())
        caps = (await shop_capabilities(session, tenant_id))["capabilities"]
        return ensure_prescription_given(
            required=bool(caps.get("prescription_required")),
            products=products,
            reference=reference,
        )

    @staticmethod
    async def record_sale(
        session: AsyncSession,
        tenant_id: UUID,
        register_id: UUID,
        *,
        items: list[dict] | None,
        customer_id: UUID | None = None,
        customer_phone: str | None = None,
        customer_name: str | None = None,
        discount_total: object = None,
        note: str | None = None,
        actor_user_id: UUID | None = None,
        discount_override: bool = False,
        payments: list[dict] | None = None,
        on_account: bool = False,
        idempotency_key: str | None = None,
        prescription: dict | None = None,
    ) -> dict:
        """RECORD a counter sale: what was sold, at what price, by whom.

        ``prescription`` (``{"number", "name"}``) is required for a prescription-only product when
        the workspace has ``prescription_required`` on; otherwise it is stored if given.

        ``on_account`` puts whatever the customer did not pay now on their credit account. It needs
        ``pos.allow_sale_on_account`` AND ``pos.take_payments`` on, a customer named on the sale
        (never the shared walk-in), and an open account with room under its limit.

        By default no payment is taken: the order is created (stock reserved), confirmed (the
        reservation becomes a real sale) and a receipt is issued with the seller on it, all in the
        caller's one transaction, and no ``OrderPayment`` or ``PosCashMovement`` is written.

        A shop that turns ``pos.take_payments`` on records how the customer paid. Each tender line
        goes through ``OrderService.add_payment`` (which keeps the over-payment guard and converts
        the stock reservation), the receipt carries the cash tendered and the change, and the cash
        that stays in the drawer is appended to the drawer ledger. A shop with the setting off that
        still sends ``payments`` is refused, never silently ignored.
        """
        OrderService = PosService._order_service()

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
        await PosService._ensure_within_discount_ceiling(
            session, tenant_id, profile, items, discount_total, override=discount_override
        )
        prescription = await PosService._check_prescription(session, tenant_id, items, prescription)
        customer_notice: str | None = None
        if customer_id is None and customer_phone and customer_phone.strip():
            from app.modules.customers.service import CustomerService

            # An OPTIONAL phone: it books the sale to the customer who owns that number so a chat
            # can find the invoice. It must never refuse the sale, but it must never be dropped
            # silently either: when it cannot be used, the cashier is told.
            phone_customer, problem = await CustomerService.find_or_create_by_phone(
                session, tenant_id, phone=customer_phone, name=customer_name
            )
            if phone_customer is not None:
                customer_id = phone_customer.id
            elif problem is not None:
                customer_notice = "phone_not_recorded"
        resolved_customer_id = await PosService._resolve_customer(
            session, tenant_id, profile, customer_id
        )

        # Decide up front whether this till takes payments, so a bad request is refused before any
        # order or reservation exists.
        take_payments = bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        )
        tender_lines = parse_lines(payments)
        account_sale = False
        if on_account:
            if not take_payments:
                raise ValidationError(
                    "selling on account needs payments recorded: turn on pos.take_payments"
                )
            if not bool(
                await PosService._setting(
                    session, tenant_id, "pos.allow_sale_on_account", pos_session
                )
            ):
                raise ValidationError(
                    "this till does not sell on account: turn on pos.allow_sale_on_account"
                )
            if customer_id is None and not (customer_phone and customer_phone.strip()):
                # the shared walk-in customer must never carry a debt nobody can chase
                raise ValidationError("a sale on account needs a named customer")
            account_sale = True
        reference_required: list[str] = []
        if take_payments:
            if not tender_lines and not account_sale:
                raise ValidationError("this till takes payments: send at least one payment line")
            reference_required = [
                str(m)
                for m in (
                    await PosService._setting(
                        session, tenant_id, "pos.reference_required_methods", pos_session
                    )
                    or []
                )
            ]
        elif tender_lines:
            raise ValidationError(
                "this till does not record payments: turn on pos.take_payments or send no payments"
            )
        else:
            # A sale with no payment recorded. For an apparel shop whose setup was skipped this is
            # exactly how money goes missing: the screen completes a normal sale, the stock leaves,
            # and no till ever recorded a pound. It is refused unless the owner has deliberately
            # turned on record-only selling.
            await PosService._ensure_record_only_is_deliberate(session, tenant_id, pos_session)

        order = await OrderService.create_order(
            session,
            tenant_id,
            resolved_customer_id,
            items,
            channel="pos",
            warehouse_id=register.warehouse_id,
            discount_total=discount_total,
            note=note,
            prescription=prescription,
        )
        tender = None
        if take_payments:
            allowed = (
                set(profile.allowed_payment_methods or []) if profile is not None else {"cash"}
            )
            tender = settle(
                tender_lines,
                total=Decimal(str(order.grand_total)),
                allowed_methods=allowed,
                reference_required=reference_required,
                allow_partial=account_sale,
            )
            for line in tender.lines:
                await OrderService.add_payment(
                    session,
                    tenant_id,
                    order.id,
                    method=line.method,
                    amount=line.amount,
                    provider=line.reference,
                    actor_user_id=actor_user_id,
                )
            if account_sale:
                # A sale on account is not settled by its payments, so no payment may be the thing
                # that confirms it: confirm it here. Idempotent, so a payment that already did is
                # not repeated and the stock leaves the shelf exactly once.
                await OrderService.confirm_sale(
                    session, tenant_id, order.id, actor_user_id=actor_user_id
                )
        else:
            await OrderService.confirm_sale(
                session, tenant_id, order.id, actor_user_id=actor_user_id
            )
        on_account_amount = Decimal("0.00")
        deposit_used = Decimal("0.00")
        if account_sale:
            from app.modules.customer_accounts.service import CustomerAccountService

            paid_now = tender.paid if tender is not None else Decimal("0.00")
            # A deposit the customer holds pays first. It comes off BEFORE the credit check so
            # the limit is judged on what is really still owed. The amount used covers part of the
            # sale, so it counts as paid: only the remainder can go on account.
            still_due = Decimal(str(order.grand_total)) - paid_now
            deposit_used = Decimal("0.00")
            if still_due > 0:
                deposit_used = await CustomerAccountService.apply_deposit_to_sale(
                    session,
                    tenant_id,
                    resolved_customer_id,
                    sale_total=still_due,
                    order_id=order.id,
                    idempotency_key=f"deposit:{idempotency_key}" if idempotency_key else None,
                    actor_user_id=actor_user_id,
                )
            paid_now += deposit_used
            entry = await CustomerAccountService.charge(
                session,
                tenant_id,
                resolved_customer_id,
                sale_total=order.grand_total,
                paid_now=paid_now,
                order_id=order.id,
                idempotency_key=f"sale:{idempotency_key}" if idempotency_key else None,
                actor_user_id=actor_user_id,
                blocked=await PosService._customer_blocked(
                    session, tenant_id, resolved_customer_id
                ),
            )
            on_account_amount = (
                Decimal(str(entry.amount)) if entry is not None else on_account_amount
            )
        has_cash = tender is not None and tender.tendered_cash is not None
        receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            tendered_amount=tender.tendered_cash if has_cash else None,
            change_amount=tender.change if has_cash else None,
            sold_by_user_id=actor_user_id,
        )
        if tender is not None and tender.cash_kept > 0:
            session.add(
                PosCashMovement(
                    tenant_id=tenant_id,
                    session_id=pos_session.id,
                    direction="in",
                    reason="cash_sale",
                    amount=tender.cash_kept,
                    reference_type="order",
                    reference_id=order.id,
                    created_by_user_id=actor_user_id,
                )
            )
            await session.flush()
        await PosService._issue_eta_receipt(session, tenant_id, pos_session, receipt)
        return {
            "order_id": order.id,
            "order_number": order.number,
            "receipt_id": receipt.id,
            "receipt_number": receipt.number,
            "grand_total": str(order.grand_total),
            "customer_notice": customer_notice,
            "paid": str(tender.paid) if tender is not None else None,
            "change": str(tender.change) if has_cash else None,
            "on_account": str(on_account_amount) if account_sale else None,
            "deposit_used": str(deposit_used) if account_sale else None,
        }

    @staticmethod
    async def _customer_blocked(session: AsyncSession, tenant_id: UUID, customer_id: UUID) -> bool:
        from app.modules.customers.service import CustomerService

        customer = await CustomerService.get(session, tenant_id, customer_id)
        return bool(customer.is_blocked)

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
        # A till's own switch wins when it is on; otherwise the shop-wide setting decides, so a
        # merchant who wants a named customer on every sale sets it once, not on each till.
        from app.modules.settings.service import SettingsService

        shop_requires = bool(
            await SettingsService(session, tenant_id).value("pos.require_customer")
        )
        if (profile is not None and profile.require_customer) or shop_requires:
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
        # Receipt numbers are a fiscal sequence: consecutive, no gaps, per tenant and year
        # (POS-2026-0001, POS-2026-0002 ...). They come from the same gap-free counter the
        # purchasing and expenses documents use, taken under a row lock in THIS transaction, so a
        # sale that rolls back gives its number back and two tills can never draw the same one.
        # A random suffix (the old scheme) cannot be audited for missing receipts.
        last_exc: IntegrityError | None = None
        for _attempt in range(_NUMBER_ATTEMPTS):
            number = await PosService._order_numbering().next_number(
                session, tenant_id, number_prefix
            )
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

    @staticmethod
    async def _issue_eta_receipt(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession, receipt: PosReceipt
    ) -> None:
        """Hand a finished till receipt to the Egyptian e-receipt layer (off unless enabled).

        Called only AFTER the receipt's lines are written, since a return's lines are what the
        e-receipt is built from. It never raises into the sale: the customer is at the counter,
        and a missing tax number or item code must not stop them leaving (see
        ``issue_for_receipt``). The register's code names the e-receipt till.
        """
        from app.modules.pos.eta_adapter import issue_for_receipt

        register = await PosService._get_register(session, tenant_id, pos_session.register_id)
        await issue_for_receipt(session, tenant_id, receipt, register_code=register.code)

    # -------------------------------------------------------------- close ----

    @staticmethod
    async def close_session(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        closed_by: UUID | None = None,
        shift_override: bool = False,
        counted_cash: object = None,
        variance_reason: object = None,
        counted_methods: object = None,
    ) -> PosSession:
        """OPEN → CLOSED. The day is RECORDED; it is counted only where the shop counts.

        By default nothing is counted: the close stores the day's closing balance, derived from
        the ledgers (opening balance + every invoice − every return; an exchange is a return plus
        a new sale, so its value difference is already inside both figures).

        A till whose ``pos.take_payments`` is on also has a drawer. Its close then needs the cash
        the cashier counted, and records the expected cash (from the drawer ledger) and the
        variance. A till with the setting off refuses a counted figure rather than ignoring it.

        A shop that takes card, wallet or transfer counts those too: ``counted_methods`` is
        ``{method: amount}`` as the terminal slip or the account statement shows it, and one
        ``PosSessionReconciliation`` row per method records expected vs counted vs the difference.
        With ``pos.settle_payment_methods`` on, every non-cash method the day collected must be
        counted — the close refuses to guess, because an unchecked card total is exactly the gap a
        real shop loses money in. With it off, only the methods the closer actually counted get a
        row, and the rest stay visibly uncounted rather than silently assumed correct.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        PosService._ensure_holds_shift(pos_session, closed_by, override=shift_override)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, closed_by, override=shift_override
        )
        if pos_session.status != "OPEN":
            raise ConflictError(f"pos session is already {pos_session.status}")
        counted: Decimal | None = None
        drawer_on = bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        )
        if drawer_on:
            if counted_cash is None:
                raise ValidationError("count the drawer: counted_cash is required to close")
            counted = to_money(counted_cash, "counted_cash")
            if counted < 0:
                raise ValidationError("counted_cash cannot be negative")
        elif counted_cash is not None or variance_reason is not None:
            raise ValidationError(
                "this till does not count a drawer: turn on pos.take_payments or send no count"
            )
        # ---- per-method settlement (card / wallet / transfer alongside the cash) ----
        method_counts = PosService._counted_methods(counted_methods)
        settle_methods = bool(
            await PosService._setting(session, tenant_id, "pos.settle_payment_methods", pos_session)
        )
        by_method: dict[str, Decimal] = {}
        if drawer_on:
            by_method = {
                str(method): Decimal(str(amount))
                for method, amount in (
                    await PosService.drawer_summary(session, tenant_id, session_id)
                )["by_method"].items()
            }
        else:
            # Even a record-only till can be asked to count the terminal, but it has no drawer
            # arithmetic to compare against; the sales' own payments are the expected figure.
            by_method = await PosService._day_by_method(session, tenant_id, pos_session)
        if not drawer_on and (counted_methods is not None or method_counts):
            raise ValidationError(
                "this till does not record payments: turn on pos.take_payments "
                "or send no counted methods"
            )
        non_cash_expected = {
            method: amount
            for method, amount in by_method.items()
            if method != CASH and to_money(amount, method) > 0
        }
        missing = sorted(set(non_cash_expected) - set(method_counts))
        if settle_methods and missing:
            raise ValidationError(
                "count every payment method before closing: "
                + ", ".join(f"{method} ({non_cash_expected[method]})" for method in missing)
            )

        expected: Decimal | None = None
        reason_to_store: str | None = None
        approved = False
        if counted is not None:
            expected = Decimal(
                (await PosService.drawer_summary(session, tenant_id, session_id))["expected_cash"]
            )
            # Everything that can refuse the close runs BEFORE the day is recorded as closed, so a
            # refusal never leaves a closed day behind.
            reason_to_store, approved = check_close_variance(
                variance_amount=variance(counted=counted, expected=expected),
                reason=variance_reason,
                reason_required=bool(
                    await PosService._setting(
                        session, tenant_id, "pos.variance_reason_required", pos_session
                    )
                ),
                approval_threshold=Decimal(
                    str(
                        await PosService._setting(
                            session, tenant_id, "pos.variance_approval_threshold", pos_session
                        )
                        or 0
                    )
                ),
                may_approve=shift_override,
            )
        await PosService._record_close(session, tenant_id, pos_session, closed_by=closed_by)
        if counted is not None and expected is not None:
            # Stored beside the day's balance: the counted figure, the cash the ledger says the
            # drawer should hold, and the difference. The ledger figure replaces the book balance
            # in ``expected_cash`` only for a till that counts, so a shop that never counts keeps
            # exactly what it had.
            pos_session.counted_cash = counted
            pos_session.expected_cash = expected
            pos_session.variance = variance(counted=counted, expected=expected)
            pos_session.variance_reason = reason_to_store
            if approved:
                pos_session.variance_approved_by_user_id = closed_by
                pos_session.variance_approved_at = datetime.now(UTC)
            await session.flush()
        # One row per method the closer counted. Cash always, because the drawer is the method the
        # till physically holds; the others when they were counted (or when the shop requires it).
        for method, counted_amount in sorted(
            {**({"cash": counted} if counted is not None else {}), **method_counts}.items()
        ):
            expected_amount = (
                expected
                if method == CASH and expected is not None
                else to_money(by_method.get(method, 0), method)
            )
            session.add(
                PosSessionReconciliation(
                    tenant_id=tenant_id,
                    session_id=pos_session.id,
                    method=method,
                    expected_amount=expected_amount,
                    counted_amount=counted_amount,
                    variance=variance(counted=counted_amount, expected=expected_amount),
                )
            )
        if counted is not None or method_counts:
            await session.flush()
        return pos_session

    @staticmethod
    def _order_numbering():
        """The gap-free document counter (lives with the expenses module that created it)."""
        from app.modules.expenses.service import NumberingService

        return NumberingService

    @staticmethod
    def _order_service():
        """The orders service, imported once for this module's payment calls.

        Imported lazily (``orders`` imports ``pos`` elsewhere) and in ONE place, so the cashier
        reaches the orders module through a single seam instead of one import per caller.
        """
        from app.modules.orders.service import OrderService

        return OrderService

    @staticmethod
    async def drawer_summary(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """What the drawer should hold and how the day was paid. Read-only, from the ledgers.

        ``expected_cash`` is the opening float plus every row of the drawer ledger, never a stored
        figure, so a missing row shows up as a variance instead of being hidden. ``by_method`` is
        what each payment method collected on the day's sales, for comparing the card total with
        the bank slip and the transfers with the account.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        rows = (
            await session.execute(
                select(
                    PosCashMovement.direction, PosCashMovement.reason, PosCashMovement.amount
                ).where(
                    PosCashMovement.tenant_id == tenant_id,
                    PosCashMovement.session_id == pos_session.id,
                )
            )
        ).all()
        expected = expected_drawer_cash(
            opening_float=to_money(pos_session.opening_float, "opening_float"),
            movements=[(r[0], r[1], Decimal(str(r[2]))) for r in rows],
        )
        sold_order_ids = list(
            (
                await session.execute(
                    select(PosReceipt.order_id).where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id == pos_session.id,
                        PosReceipt.kind == "sale",
                    )
                )
            )
            .scalars()
            .all()
        )
        collected = await PosService._order_service().collected_by_method(
            session, tenant_id, sold_order_ids
        )
        return {
            "session_id": pos_session.id,
            "opening_float": str(to_money(pos_session.opening_float, "opening_float")),
            "expected_cash": str(expected),
            "counted_cash": (
                str(pos_session.counted_cash) if pos_session.counted_cash is not None else None
            ),
            "variance": str(pos_session.variance) if pos_session.variance is not None else None,
            "by_method": {m: str(a) for m, a in collected.items()},
        }

    @staticmethod
    async def handover_session(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        new_cashier_id: UUID,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
        counted_cash: object = None,
        variance_reason: object = None,
    ) -> PosSession:
        """Transfer the drawer to another cashier without closing the day.

        The hand-off is COUNTED, not just reassigned: ``counted_cash`` is what the new cashier
        finds in the drawer, the session's own arithmetic says what should be there, and the
        difference is stored on a ``PosSessionHandover`` row naming both people. Without that row
        the day's shortage could never be pinned on the shift it happened in — the session keeps
        running and every later figure would be attributed to whoever holds it last.

        A till that does not take payments has no drawer to count and records the hand-over with
        the arithmetic at zero.
        """
        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        if pos_session.status != "OPEN":
            raise ConflictError("cannot hand over a closed session")
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, new_cashier_id, override=shift_override
        )
        drawer_on = bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        )
        expected = Decimal("0.00")
        counted = Decimal("0.00")
        if drawer_on:
            expected = Decimal(
                (await PosService.drawer_summary(session, tenant_id, session_id))["expected_cash"]
            )
            if counted_cash is None:
                raise ValidationError("count the drawer: counted_cash is required to hand it over")
            counted = to_money(counted_cash, "counted_cash")
            if counted < 0:
                raise ValidationError("counted_cash cannot be negative")
            short = variance(counted=counted, expected=expected)
            reason_to_store, _approved = check_close_variance(
                variance_amount=short,
                reason=variance_reason,
                reason_required=bool(
                    await PosService._setting(
                        session, tenant_id, "pos.variance_reason_required", pos_session
                    )
                ),
                approval_threshold=Decimal(
                    str(
                        await PosService._setting(
                            session, tenant_id, "pos.variance_approval_threshold", pos_session
                        )
                        or 0
                    )
                ),
                may_approve=shift_override,
            )
        else:
            reason_to_store = str(variance_reason).strip()[:255] if variance_reason else None
        session.add(
            PosSessionHandover(
                tenant_id=tenant_id,
                session_id=pos_session.id,
                from_user_id=pos_session.cashier_user_id or actor_user_id,
                to_user_id=new_cashier_id,
                expected_cash=expected,
                counted_cash=counted,
                variance=variance(counted=counted, expected=expected),
                note=reason_to_store,
            )
        )
        pos_session.cashier_user_id = new_cashier_id
        await session.flush()
        return pos_session

    # ------------------------------------------------- close-time settlement ----

    @staticmethod
    def _counted_methods(raw: object) -> dict[str, Decimal]:
        """Validate ``{method: amount}`` as the closer typed it.

        A method outside the till's vocabulary is a 422, never a silent no-op: a typo in a method
        name would otherwise drop a whole terminal's count on the floor.
        """
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ValidationError("counted_methods must be an object of {method: amount}")
        counts: dict[str, Decimal] = {}
        for method, amount in raw.items():
            name = str(method).strip()
            if name not in PAYMENT_METHODS:
                raise ValidationError(
                    f"unknown payment method {name!r}; allowed {list(PAYMENT_METHODS)}"
                )
            value = to_money(amount, f"counted {name}")
            if value < 0:
                raise ValidationError(f"counted {name} cannot be negative")
            counts[name] = value
        return counts

    @staticmethod
    async def _day_by_method(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> dict[str, Decimal]:
        """What each method collected on the day's sales, from the payments themselves."""
        order_ids = list(
            (
                await session.execute(
                    select(PosReceipt.order_id).where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id == pos_session.id,
                        PosReceipt.kind == "sale",
                    )
                )
            )
            .scalars()
            .all()
        )
        return await PosService._order_service().collected_by_method(session, tenant_id, order_ids)

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
                    # A VOIDED sale is not a sale: its receipt still exists (the audit trail needs
                    # it) but it must not inflate the shift's count or total, or the Z report would
                    # disagree with the day's takings the moment a cashier voids an invoice.
                    Order.status != "cancelled",
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
                    # A voided sale is not a sale: it was reversed the same day, and counting it
                    # here would show revenue the shop never kept.
                    Order.status != "cancelled",
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
        voids_out: list[dict] = []
        for r in receipts:
            if r.kind == "void":
                # A void is not a return: it says the sale never happened, so it is reported on its
                # own line with the invoice it reverses.
                voids_out.append(
                    {
                        "receipt_id": str(r.id),
                        "receipt_number": r.number,
                        "issued_at": r.issued_at.isoformat(),
                        "original_order_id": str(r.order_id),
                        "total": str(sale_total.get(r.id, Decimal("0"))),
                    }
                )
            elif r.kind == "return":
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
        return {"returns": returns_out, "exchanges": exchanges_out, "voids": voids_out}

    # ------------------------------------------------------- close preview ----

    @staticmethod
    async def close_preview(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> dict:
        """What the close will record: the day's figures and the closing balance. Read-only."""
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        totals = await PosService._day_totals(session, tenant_id, pos_session)
        drawer_on = bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        )
        # What each method should hold, so the screen can ask for the terminal counts too and show a
        # gap per method instead of one cash figure. A record-only till reads its sales' payments.
        by_method = (
            (await PosService.drawer_summary(session, tenant_id, session_id))["by_method"]
            if drawer_on
            else await PosService._day_by_method(session, tenant_id, pos_session)
        )
        return {
            "session_id": pos_session.id,
            "status": pos_session.status,
            # Whether this close counts a drawer. The screen asks for the count only then, so it can
            # never disagree with ``close_session``, which refuses a close that lacks one.
            "take_payments": drawer_on,
            # Whether every non-cash method must be counted, and what each one should hold.
            "settle_payment_methods": bool(
                await PosService._setting(
                    session, tenant_id, "pos.settle_payment_methods", pos_session
                )
            ),
            "by_method": {str(k): str(v) for k, v in by_method.items()},
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
    async def cashier_custody(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Per cashier over ``[start, end)``: the cash they were answerable for and how far off.

        Built from shifts CLOSED in the period, in one grouped query. Only a shift that counted
        its drawer has cash to account for: one that did not (the till takes no payments) adds to
        the shift count but to no money figure, so it can never read as a perfect zero. The
        biggest shortfall comes first, because that is the row the owner needs to see.
        """
        if end <= start:
            raise ValidationError("the period must end after it starts")
        counted = PosSession.counted_cash.is_not(None)
        var = PosSession.variance
        shortage = func.coalesce(func.sum(case((counted & (var < 0), -var), else_=0)), 0)
        overage = func.coalesce(func.sum(case((counted & (var > 0), var), else_=0)), 0)
        rows = (
            await session.execute(
                select(
                    PosSession.cashier_user_id,
                    func.count(PosSession.id),
                    func.count(PosSession.counted_cash),
                    func.coalesce(func.sum(PosSession.expected_cash).filter(counted), 0),
                    func.coalesce(func.sum(PosSession.counted_cash), 0),
                    func.coalesce(func.sum(var).filter(counted), 0),
                    shortage,
                    overage,
                    func.count(PosSession.id).filter(counted & (var != 0)),
                    func.count(PosSession.variance_approved_by_user_id),
                )
                .where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.status == "CLOSED",
                    PosSession.closed_at >= start,
                    PosSession.closed_at < end,
                )
                .group_by(PosSession.cashier_user_id)
            )
        ).all()
        out = [
            {
                "cashier_user_id": str(r[0]) if r[0] is not None else None,
                "shifts": r[1],
                "counted_shifts": r[2],
                "expected_cash": str(to_money(r[3], "expected")),
                "counted_cash": str(to_money(r[4], "counted")),
                "net_variance": str(to_money(r[5], "variance")),
                "shortage_total": str(to_money(r[6], "shortage")),
                "overage_total": str(to_money(r[7], "overage")),
                "shifts_with_variance": r[8],
                "approved_variances": r[9],
            }
            for r in rows
        ]
        out.sort(key=lambda row: (-Decimal(row["shortage_total"]), row["cashier_user_id"] or ""))
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
            "voids": {
                "void_count": len(docs["voids"]),
                "documents": docs["voids"],
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
                        # Voided invoices are history, not takings: the day's rollup is what the
                        # owner compares against the bank, so it counts what was actually sold.
                        Order.status != "cancelled",
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
    def _clean_receipt_email(email: object) -> str:
        """One strict address or a ValidationError: no lists, no whitespace, no header injection."""
        from email_validator import EmailNotValidError, validate_email

        raw = str(email).strip()
        if len(raw) > 254 or any(ch in raw for ch in ("\r", "\n", ",", ";", " ")):
            raise ValidationError("a valid email address is required")
        try:
            return validate_email(raw, check_deliverability=False).normalized
        except EmailNotValidError:
            raise ValidationError("a valid email address is required") from None

    # Ceilings on "email me this receipt", over a rolling day. They guard abuse of the shop's own
    # sending domain (one receipt mailed over and over, or one stranger's address aimed at from many
    # receipts); they are not a shop policy, so they are fixed.
    RECEIPT_EMAIL_PER_RECEIPT_PER_DAY = 5
    RECEIPT_EMAIL_PER_ADDRESS_PER_DAY = 20

    @staticmethod
    def _receipt_email_key(address: str) -> str:
        """One key per MAILBOX, so the per-address cap cannot be got round by respelling it.

        Lower-cased always. For Gmail (``gmail.com`` and ``googlemail.com`` are one service) the
        dots in the name are ignored and everything after a ``+`` is a tag, so ``v.i.c+1@`` and
        ``vic@`` reach the same inbox. Other providers are left alone: a dot or a ``+`` can be
        significant there, and merging them would block two real, different customers.
        """
        local, _, domain = address.strip().lower().rpartition("@")
        if domain in ("gmail.com", "googlemail.com"):
            local = local.split("+", 1)[0].replace(".", "")
            domain = "gmail.com"
        return f"{local}@{domain}"

    @staticmethod
    async def _ensure_receipt_email_room(
        session: AsyncSession, tenant_id: UUID, receipt_id: UUID, address: str
    ) -> None:
        """Refuse (429) when this receipt or this address has used up the day's room.

        Counted from the requests already staged in the outbox, so nothing new is stored and a
        refused request stages nothing. Plain SQL on purpose: pos must not import the platform
        module just to count its own events. The address is compared lower-cased, so changing its
        case does not escape the count. Only this shop's requests count.
        """
        from sqlalchemy import text

        from app.core.errors import RateLimitExceededError

        # Count and insert are two steps. Without this, requests that arrive together all read the
        # same count and all pass, so the cap held for one-at-a-time callers only. One lock per
        # shop makes them queue; it is released with the transaction, which also holds the insert.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"receipt_email:{tenant_id}"},
        )
        key = PosService._receipt_email_key(address)
        row = (
            await session.execute(
                text(
                    "SELECT"
                    " count(*) FILTER (WHERE payload->>'receipt_id' = :receipt),"
                    " count(*) FILTER (WHERE coalesce(payload->>'email_key',"
                    " lower(payload->>'email')) = :key)"
                    " FROM outbox_events"
                    " WHERE payload->>'event_type' = 'pos.receipt.email_requested'"
                    " AND meta->>'tenant_id' = :tenant"
                    " AND created_at > now() - interval '1 day'"
                ),
                {"receipt": str(receipt_id), "key": key, "tenant": str(tenant_id)},
            )
        ).one()
        if row[0] >= PosService.RECEIPT_EMAIL_PER_RECEIPT_PER_DAY:
            raise RateLimitExceededError(
                "this receipt was already emailed several times today; try again tomorrow"
            )
        if row[1] >= PosService.RECEIPT_EMAIL_PER_ADDRESS_PER_DAY:
            raise RateLimitExceededError(
                "too many receipts were sent to this address today; try again tomorrow"
            )

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
        cleaned = PosService._clean_receipt_email(email)
        await PosService._ensure_receipt_email_room(session, tenant_id, receipt.id, cleaned)

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
                "email_key": PosService._receipt_email_key(cleaned),
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
        if not await PosService._setting(session, tenant_id, "pos.allow_hold_cart", pos_session):
            raise ConflictError("holding a cart is turned off for this till (pos.allow_hold_cart)")
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
        restock: bool | None = None,
        refund: object = None,
        refund_method: str | None = None,
        refund_references: dict[str, str] | None = None,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> dict:
        """Record the goods coming back AND give the money back.

        Two documents, one transaction:

        1. the **goods** — each line capped at sold-minus-already-returned and valued at the
           ORIGINAL line's unit price minus its discount share, on a return receipt (``POS-RET-``)
           that every later return caps against. ``restock`` puts the returned quantities back on
           the register's shelf.
        2. the **money** — the return value is refunded across the tenders the sale actually
           collected, per ``app.modules.pos.refund``: cash first, then the rest in the order they
           were taken, each tender never giving back more than it holds. Every slice writes a
           ``Refund`` row against that payment, and the cash part writes an ``out`` row on the
           drawer ledger (``cash_refund``), so the close arithmetic sees it.

        A till with ``pos.take_payments`` off moves no money at all: it records the return and
        reports the value as ``uncollected``, which is exactly what its sales did too.

        ``refund`` overrides the policy with explicit ``[{method, amount}]`` pairs (give the notes
        back even though the card was charged, when the terminal is down). Each pair must be
        satisfiable from that method's own remaining room, so the refund still points at a real
        payment. ``refund_method`` names a single method instead — a shortcut for one pair.

        A retry of the same request must carry the same ``Idempotency-Key`` header: the platform
        refuses a second execution of a key it already completed, so a dropped connection cannot
        refund twice.
        """
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.models import InventoryMovement
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
        await PosService._ensure_within_window(
            session,
            tenant_id,
            pos_session,
            receipt.issued_at,
            key="pos.return_max_days",
            what="return",
        )
        restock = await PosService._resolve_restock(session, tenant_id, pos_session, restock)
        shelf = PosService._line_restock(lines, restock)
        reasons = await PosService._clean_return_reasons(session, tenant_id, pos_session, lines)
        conditions = PosService._return_conditions(lines)
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

        shelved = {v: q for v, q in requested.items() if shelf.get(v)}
        if shelved:
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
            for variant_id, quantity in shelved.items():
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
                "reason": reasons.get(variant_id),
                "condition": conditions.get(variant_id, "sellable"),
            }
            for variant_id, total in zip(requested, priced, strict=True)
        ]
        refund_total = to_money(
            sum((entry["refund_total"] for entry in refund_lines), Decimal("0")),
            "refund_total",
        )
        # The money half. ``settlement`` says what was actually given back, on which tender, and
        # what part of the return value the sale never collected (on account, or a deposit).
        settlement = await PosService._settle_refund(
            session,
            tenant_id,
            pos_session,
            order,
            refund_total,
            requested=PosService._refund_request(refund),
            single_method=refund_method,
            reason=PosService._refund_reason(refund_lines),
            actor_user_id=actor_user_id,
            references=refund_references,
        )

        restocked = False
        if shelved:
            register = await PosService._get_register(session, tenant_id, pos_session.register_id)
            for entry in refund_lines:
                if not shelf.get(entry["variant_id"]):
                    continue
                # The CONDITION decides the destination, not the fact that a return happened. A
                # torn dress must not go back on the sellable shelf, and goods on their way to the
                # supplier are not stock at all.
                if await PosService._restock_returned(
                    session,
                    tenant_id,
                    entry,
                    register.warehouse_id,
                    order_id=order_id,
                    actor_user_id=actor_user_id,
                ):
                    restocked = True
            restocked = True

        return_receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            number_prefix="POS-RET",
            kind="return",
            sold_by_user_id=actor_user_id,
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
                    reason=entry["reason"],
                    condition=entry["condition"],
                )
            )
        await session.flush()
        await PosService._issue_eta_receipt(session, tenant_id, pos_session, return_receipt)

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
                "refund_mode": settlement["mode"],
                "refunded": str(settlement["refunded"]),
                "refund_by_method": {m: str(a) for m, a in settlement["by_method"].items()},
                "refund_uncollected": str(settlement["uncollected"]),
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
            },
            producer="pos",
        )
        return {
            "receipt_id": return_receipt.id,
            "receipt_number": return_receipt.number,
            "refunded_total": str(refund_total),
            # The money that actually moved, and how. ``refund_mode`` is ``tender`` (refunded
            # across the original tenders), ``record_only`` (a till that takes no payments), or
            # ``nothing_collected`` (the sale never collected this value).
            "refund_mode": settlement["mode"],
            "refunded": str(settlement["refunded"]),
            "refund_by_method": {m: str(a) for m, a in settlement["by_method"].items()},
            "refund_uncollected": str(settlement["uncollected"]),
            # A card/wallet slice is promised, not yet proven: the cashier reverses it on the
            # terminal and confirms it with the reference. Until then nothing derived has moved.
            "awaiting_confirmation": settlement.get("awaiting_confirmation", []),
            # A cash-only shop never records a non-cash reversal; this is what to reverse by hand.
            "terminal_only": settlement.get("terminal_only", []),
            "refunds": [
                {
                    "payment_id": str(slice_.payment_id) if slice_.payment_id else None,
                    "method": slice_.method,
                    "amount": str(slice_.amount),
                }
                for slice_ in settlement["slices"]
            ],
            "lines": [
                {
                    "variant_id": str(entry["variant_id"]),
                    "quantity": entry["quantity"],
                    "refund_total": str(entry["refund_total"]),
                    "restocked": bool(shelf.get(entry["variant_id"])),
                }
                for entry in refund_lines
            ],
            # True when at least one piece went back on the shelf; each line says its own.
            "restocked": restocked,
        }

    @staticmethod
    async def _ensure_record_only_is_deliberate(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession
    ) -> None:
        """Refuse a silent record-only sale in a shop that never chose it.

        ``pos.take_payments`` defaults to off, and an apparel shop that skipped its setup keeps
        that default. Selling in that state looks completely normal and records no money at all, so
        the shop only finds out when the drawer and the books disagree. The owner can still run
        this way on purpose: ``pos.allow_record_only_sales`` is the explicit yes.
        """
        mode = await PosService.payments_mode(session, tenant_id, pos_session)
        if not mode["apparel_setup_incomplete"]:
            return
        if bool(
            await PosService._setting(
                session, tenant_id, "pos.allow_record_only_sales", pos_session
            )
        ):
            return
        raise ValidationError(
            "this apparel till records sales but no payments: finish the shop setup so the till "
            "takes payments, or turn on pos.allow_record_only_sales to sell without collecting "
            "on purpose"
        )

    #: The states a returned garment can come back in. The condition, not the return itself,
    #: decides whether the unit is stock again and whether it can be sold.
    RETURN_CONDITIONS = ("sellable", "quarantine", "damaged", "writeoff", "supplier")
    #: Conditions where the goods are physically in the shop but NOT sellable: they are counted in
    #: `on_hand` and in `quarantined`, so availability (on_hand - quarantined - reserved) never
    #: offers them to a customer.
    _UNSELLABLE_CONDITIONS = frozenset({"quarantine", "damaged"})

    @staticmethod
    def _return_conditions(lines: list[dict]) -> dict[UUID, str]:
        """The condition per variant, from the return lines. Defaults to ``sellable``."""
        conditions: dict[UUID, str] = {}
        for line in lines:
            raw = line.get("condition")
            if raw in (None, ""):
                continue
            value = str(raw).strip().lower()
            if value not in PosService.RETURN_CONDITIONS:
                raise ValidationError(
                    f"condition must be one of {list(PosService.RETURN_CONDITIONS)}"
                )
            try:
                conditions[UUID(str(line["variant_id"]))] = value
            except (KeyError, ValueError):
                continue
        return conditions

    @staticmethod
    async def _restock_returned(
        session: AsyncSession,
        tenant_id: UUID,
        entry: dict,
        warehouse_id: UUID,
        *,
        order_id: UUID,
        actor_user_id: UUID | None,
    ) -> bool:
        """Put a returned line where its CONDITION says it belongs. Returns whether stock moved.

        * ``sellable``  — back on the shelf, available to sell again.
        * ``quarantine``/``damaged`` — physically in the shop, counted in ``on_hand`` and in
          ``quarantined``, so availability never offers it. It waits for inspection, a repair or a
          supplier claim.
        * ``writeoff`` — destroyed or lost. Nothing returns to stock: counting it would inflate the
          shelf and hide the loss.
        * ``supplier`` — going back to the supplier. Also not stock.
        """
        from app.modules.inventory.service import InventoryService
        from app.modules.inventory.services.balances import BalanceServiceMixin

        condition = entry.get("condition") or "sellable"
        if condition in {"writeoff", "supplier"}:
            return False
        await InventoryService.move(
            session,
            tenant_id,
            entry["variant_id"],
            warehouse_id,
            direction="in",
            quantity=entry["quantity"],
            reason="return",
            reference_type="order",
            reference_id=order_id,
            actor_user_id=actor_user_id,
        )
        if condition in PosService._UNSELLABLE_CONDITIONS:
            balance = await BalanceServiceMixin._locked_balance(
                session, tenant_id, entry["variant_id"], warehouse_id
            )
            balance.quarantined = int(balance.quarantined or 0) + int(entry["quantity"])
        return True

    # ---------------------------------------------------------- void a sale ----

    @staticmethod
    async def void_sale(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        order_id: UUID,
        reason: object,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> dict:
        """Reverse a CONFIRMED sale. Nothing is deleted: a reversing document is added.

        A return and a void are different accounting facts and the till keeps them apart. A return
        says "the customer brought goods back"; a void says "this sale should never have existed"
        — the wrong size rung up, the wrong price, the wrong colour. Using a return for the second
        pollutes the return report with sales that never happened.

        So a void:

        * needs a manager override (``shift_override``) and a reason;
        * puts every unit back on the shelf as its own ``void`` movement;
        * gives the money back across the tenders the sale collected, through the same
          ``_settle_refund`` a return uses, so the drawer and the card reversals agree;
        * issues a ``POS-VOID-`` receipt against the original order;
        * announces ``pos.sale.voided`` with the original and the actor.

        Refused when any of the sale has already come back: a half-returned, half-voided sale has
        no single meaning. Finish it as a return instead.
        """
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.stock_view import VoidGateway
        from app.modules.orders.models import Order, OrderItem

        reason_text = str(reason or "").strip()
        if not reason_text:
            raise ValidationError("a void needs a reason")
        if len(reason_text) > 255:
            raise ValidationError("the void reason must be at most 255 characters")

        pos_session = await PosService._get_session(session, tenant_id, session_id, lock=True)
        PosService._ensure_holds_shift(pos_session, actor_user_id, override=shift_override)
        await PosService._ensure_may_operate(
            session, tenant_id, pos_session, actor_user_id, override=shift_override
        )
        if not shift_override:
            raise PermissionDeniedError("voiding a confirmed sale needs a manager override")
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; a void rides the open drawer")

        order = (
            await session.execute(
                select(Order)
                .where(Order.tenant_id == tenant_id, Order.id == order_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError(f"order {order_id} not found")

        sale_receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.order_id == order_id,
                    PosReceipt.kind == "sale",
                )
            )
        ).scalar_one_or_none()
        if sale_receipt is None:
            raise NotFoundError(f"no POS sale receipt for order {order_id}")
        already = (
            await session.execute(
                select(PosReceipt.id).where(
                    PosReceipt.tenant_id == tenant_id,
                    PosReceipt.order_id == order_id,
                    PosReceipt.kind == "void",
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            raise ConflictError("this sale was already voided")
        came_back = (
            await session.execute(
                select(func.coalesce(func.sum(PosReturnLine.quantity), 0)).where(
                    PosReturnLine.tenant_id == tenant_id,
                    PosReturnLine.order_id == order_id,
                )
            )
        ).scalar_one()
        if int(came_back or 0) > 0:
            raise ConflictError(
                "part of this sale already came back as a return; "
                "finish it as a return instead of a void"
            )

        register = await PosService._get_register(session, tenant_id, pos_session.register_id)
        items = list(
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id, OrderItem.order_id == order_id
                    )
                )
            )
            .scalars()
            .all()
        )
        # Back on the shelf, each piece at the cost the sale booked for it. Inventory owns both
        # rules (the movement and the restored cost layer), so the till asks its gateway.
        await VoidGateway.restore_sold_stock(
            session,
            tenant_id,
            order_id=order_id,
            warehouse_id=register.warehouse_id,
            lines=[(item.variant_id, int(item.quantity)) for item in items],
            actor_user_id=actor_user_id,
        )

        # The order is no longer a sale: every report that reads order status must drop it, and a
        # second void must find it already reversed.
        order.status = "cancelled"

        # Give back exactly what the sale collected, on the tenders that collected it.
        tenders, _payments = await PosService._refundable_tenders(session, tenant_id, order_id)
        collected = to_money(sum((tender.room for tender in tenders), Decimal("0")), "collected")
        settlement = await PosService._settle_refund(
            session,
            tenant_id,
            pos_session,
            order,
            collected,
            reason=f"void: {reason_text}",
            actor_user_id=actor_user_id,
        )

        void_receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            number_prefix="POS-VOID",
            kind="void",
            sold_by_user_id=actor_user_id,
        )
        await session.flush()
        await add_outbox_event(
            session,
            aggregate_type="pos_session",
            aggregate_id=pos_session.id,
            event_type="pos.sale.voided",
            tenant_id=tenant_id,
            payload={
                "pos.sale.voided": True,
                "session_id": str(pos_session.id),
                "order_id": str(order_id),
                "original_receipt_id": str(sale_receipt.id),
                "original_receipt_number": sale_receipt.number,
                "void_receipt_id": str(void_receipt.id),
                "reason": reason_text,
                "refunded": str(settlement["refunded"]),
                "refund_by_method": {m: str(a) for m, a in settlement["by_method"].items()},
                "uncollected": str(settlement["uncollected"]),
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
            },
            producer="pos",
        )
        return {
            "void_receipt_id": void_receipt.id,
            "void_receipt_number": void_receipt.number,
            "order_id": order_id,
            "original_receipt_id": sale_receipt.id,
            "original_receipt_number": sale_receipt.number,
            "reason": reason_text,
            "refunded": str(settlement["refunded"]),
            "refund_by_method": {m: str(a) for m, a in settlement["by_method"].items()},
            "uncollected": str(settlement["uncollected"]),
            "restocked": True,
        }

    # ---------------------------------------------------- refund settlement ----

    @staticmethod
    def _refund_request(refund: object) -> list[tuple[str, object]] | None:
        """Turn the request's explicit refund lines into ``(method, amount)`` pairs, or None.

        ``None`` means "the shop's policy" — cash first, then the tenders in the order they were
        taken (``app.modules.pos.refund``). An explicit list is the cashier overriding that: give
        the notes back even though the card was charged, when the terminal is down.
        """
        if refund is None:
            return None
        if not isinstance(refund, (list, tuple)):
            raise ValidationError("refund must be a list of {method, amount} lines")
        pairs: list[tuple[str, object]] = []
        for index, item in enumerate(refund):
            if not isinstance(item, dict):
                raise ValidationError(f"refund[{index}] must be an object")
            method = str(item.get("method", "")).strip()
            if not method:
                raise ValidationError(f"refund[{index}].method is required")
            pairs.append((method, item.get("amount")))
        return pairs or None

    @staticmethod
    def _refund_reason(refund_lines: list[dict]) -> str:
        """One human line for the Refund rows: the return reasons the cashier picked."""
        picked = sorted({str(entry["reason"]) for entry in refund_lines if entry.get("reason")})
        if not picked:
            return "POS return"
        return "POS return: " + ", ".join(picked)

    @staticmethod
    async def _refundable_tenders(
        session: AsyncSession, tenant_id: UUID, order_id: UUID
    ) -> tuple[list[Tender], list]:
        """The tenders that took money and how much of each has already gone back.

        A payment that MONEY ARRIVED ON counts, whatever its later state: ``captured``, but also
        ``partially_refunded`` and ``refunded``, because the first partial refund flips the row to
        ``partially_refunded`` and the second return on the same invoice must still find its tender.
        Filtering on ``captured`` alone made the second partial refund of one tender impossible (it
        reported the value as never collected and paid nothing out).

        What did NOT take money stays out: pending, failed, cancelled. Refunds already made are
        summed per payment, which is what caps the next one — no separate counter to drift — and a
        pending (unconfirmed) refund is counted there too, so a customer cannot be paid twice while
        the terminal reversal is still unconfirmed.
        """
        from app.modules.orders.models import OrderPayment, Refund

        payments = list(
            (
                await session.execute(
                    select(OrderPayment)
                    .where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id == order_id,
                        OrderPayment.status.in_(REFUNDABLE_PAYMENT_STATES),
                    )
                    .order_by(OrderPayment.paid_at.asc().nullsfirst(), OrderPayment.id)
                )
            )
            .scalars()
            .all()
        )
        if not payments:
            return [], []
        refunded = dict(
            (
                await session.execute(
                    select(Refund.payment_id, func.coalesce(func.sum(Refund.amount), 0))
                    .where(
                        Refund.tenant_id == tenant_id,
                        Refund.payment_id.in_([payment.id for payment in payments]),
                        Refund.status.in_(REFUND_COUNTED_STATES),
                    )
                    .group_by(Refund.payment_id)
                )
            ).all()
        )
        tenders = [
            Tender(
                payment_id=payment.id,
                method=str(payment.method),
                amount=to_money(payment.amount, "payment"),
                refunded=to_money(refunded.get(payment.id, 0), "refunded"),
            )
            for payment in payments
        ]
        return tenders, payments

    @staticmethod
    async def _settle_refund(
        session: AsyncSession,
        tenant_id: UUID,
        pos_session: PosSession,
        order: object,
        amount: object,
        *,
        requested: list[tuple[str, object]] | None = None,
        single_method: str | None = None,
        reason: str | None = None,
        actor_user_id: UUID | None = None,
        references: dict[str, str] | None = None,
    ) -> dict:
        """Give the money back, across the tenders the sale collected.

        The ONE place a POS refund moves money, shared by a return, an exchange's cheaper
        replacement and a voided sale — so the three can never disagree about which tender paid.

        Writes, in the caller's transaction:
        * one ``Refund`` row per tender slice (``processed``, naming the payment it reverses);
        * one ``out`` row on the drawer ledger for the cash part (``cash_refund``), which is what
          makes the close arithmetic show the money that left the drawer.

        Cash is finished here: the notes leave the drawer in front of the customer. A CARD or
        WALLET reversal is not finished here, because the reversal happens on the shop's terminal,
        not in this database. Such a slice is written ``pending`` and named in
        ``awaiting_confirmation`` until the cashier records the terminal's reference through
        :meth:`confirm_refund`. ``references`` ({method: terminal reference}) records the ones the
        cashier already has, so a shop that types the RRN up front never leaves a pending row.
        Reporting the money as returned before the terminal confirmed it is exactly the bug this
        prevents: the books said refunded while the customer's card still held the money.

        Nothing is written for a till with ``pos.take_payments`` off, nor for value the sale never
        collected. Both cases are reported, never silently dropped: ``mode`` says which happened.
        A shop that refunds cash only (``pos.refund_cash_only``) never writes a non-cash slice at
        all; that value comes back in ``terminal_only`` for the cashier to reverse by hand.
        """
        from app.modules.orders.models import Refund

        value = to_money(amount, "refund_total")
        record_only = {
            "mode": "record_only",
            "refunded": to_money(0, "refunded"),
            "uncollected": value,
            "by_method": {},
            "slices": [],
            "awaiting_confirmation": [],
            "terminal_only": [],
        }
        if not bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        ):
            return record_only
        tenders, _payments = await PosService._refundable_tenders(session, tenant_id, order.id)
        if not tenders:
            # A sale that collected nothing has no tender to give back to. The value is reported as
            # uncollected so the caller can tell the customer what actually happened.
            return {**record_only, "mode": "nothing_collected"}
        cash_only = bool(
            await PosService._setting(session, tenant_id, "pos.refund_cash_only", pos_session)
        )
        terminal_only: list[dict] = []
        if cash_only:
            # A shop that starts cash-only must not have the till claim a card reversal it cannot
            # perform. The non-cash tenders are named for the cashier to reverse on the terminal
            # by hand, and no Refund row is written for them.
            kept = [tender for tender in tenders if tender.method == CASH]
            dropped: dict[str, Decimal] = {}
            for tender in tenders:
                if tender.method != CASH and tender.room > 0:
                    dropped[tender.method] = dropped.get(tender.method, Decimal("0")) + tender.room
            tenders = kept
            terminal_only = [
                {"method": method, "amount": str(to_money(amount_, method))}
                for method, amount_ in dropped.items()
            ]
            if not tenders:
                return {
                    **record_only,
                    "mode": "cash_only",
                    "uncollected": to_money(0, "uncollected"),
                    "terminal_only": terminal_only,
                }
        if single_method:
            plan = plan_for(value, tenders, requested=[(single_method, value)])
        else:
            plan = plan_for(value, tenders, requested=requested)
        now = datetime.now(UTC)
        references = {
            str(method): str(reference).strip()
            for method, reference in (references or {}).items()
            if str(reference).strip()
        }
        written: list[Refund] = []
        for slice_ in plan.slices:
            # Cash is done the moment it is handed over. Anything else waits for the terminal's
            # own confirmation, which is the reference below.
            confirmed = slice_.method == CASH or slice_.method in references
            row = Refund(
                tenant_id=tenant_id,
                payment_id=slice_.payment_id,
                amount=slice_.amount,
                reason=reason,
                status="processed" if confirmed else "pending",
                processed_at=now if confirmed else None,
                external_reference=references.get(slice_.method),
                created_by_user_id=actor_user_id,
            )
            session.add(row)
            written.append(row)
        if plan.cash > 0:
            session.add(
                PosCashMovement(
                    tenant_id=tenant_id,
                    session_id=pos_session.id,
                    direction="out",
                    reason="cash_refund",
                    amount=plan.cash,
                    reference_type="order",
                    reference_id=order.id,
                    notes=(reason or "POS refund")[:255],
                    created_by_user_id=actor_user_id,
                )
            )
        await session.flush()

        # The money is back, so the two DERIVED facts have to follow it, exactly as the shared
        # refund path (``OrderService.register_refund``) does. Skipping them left a POS-refunded
        # sale still reading "captured" on the order and the customer still worth money the shop
        # had already given back — so lifetime value, segments and the payment's own state
        # disagreed with the refunds that caused them.
        touched = [slice_.payment_id for slice_ in plan.slices if slice_.payment_id is not None]
        if touched:
            from app.modules.orders.service import OrderService

            await OrderService.apply_refunded_payment_states(session, tenant_id, order, touched)

        # What the terminal still has to confirm, one entry per pending slice. The method lives on
        # the slice, so the two are zipped rather than re-derived from the payment row.
        awaiting = [
            {
                "refund_id": str(row.id),
                "method": slice_.method,
                "amount": str(to_money(row.amount, "refund")),
            }
            for row, slice_ in zip(written, plan.slices, strict=True)
            if row.status == "pending"
        ]
        return {
            "mode": "tender",
            "refunded": plan.refunded,
            "uncollected": plan.uncollected,
            "by_method": plan.by_method,
            "slices": list(plan.slices),
            "awaiting_confirmation": awaiting,
            "terminal_only": terminal_only,
        }

    @staticmethod
    async def confirm_refund(
        session: AsyncSession,
        tenant_id: UUID,
        refund_id: UUID,
        external_reference: object,
        *,
        actor_user_id: UUID | None = None,
    ) -> dict:
        """The cashier's confirmation that a card/wallet reversal really happened.

        A non-cash refund is written ``pending`` because the money leaves the shop's terminal, not
        this database. This is the other half of that promise: the cashier reverses it on the
        terminal, types the terminal's own reference (RRN, approval code, transfer number), and
        only then does the refund become ``processed`` — and only then do the derived facts move
        (payment state, lifetime value), through the same rule the shared refund path uses.

        Confirming the same refund twice is refused rather than silently accepted: the second
        confirmation is a different reversal, and it must be a new refund.
        """
        from app.modules.errors import ConflictError
        from app.modules.orders.models import Order, OrderPayment, Refund
        from app.modules.orders.service import OrderService

        reference = str(external_reference or "").strip()
        if not reference:
            raise ValidationError("a card or wallet reversal needs the terminal's reference")
        row = (
            await session.execute(
                select(Refund).where(Refund.tenant_id == tenant_id, Refund.id == refund_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise ValidationError("no such refund")
        if row.status != "pending":
            raise ConflictError(f"refund {refund_id} is already {row.status}")
        payment = (
            await session.execute(
                select(OrderPayment).where(
                    OrderPayment.tenant_id == tenant_id, OrderPayment.id == row.payment_id
                )
            )
        ).scalar_one_or_none()
        if payment is None:
            raise ValidationError("the refunded payment no longer exists")
        order = (
            await session.execute(
                select(Order).where(Order.tenant_id == tenant_id, Order.id == payment.order_id)
            )
        ).scalar_one_or_none()
        if order is None:
            raise ValidationError("the refunded order no longer exists")

        row.status = "processed"
        row.processed_at = datetime.now(UTC)
        row.external_reference = reference[:64]
        await session.flush()
        await OrderService.apply_refunded_payment_states(session, tenant_id, order, [payment.id])
        await session.flush()
        return {
            "refund_id": str(row.id),
            "order_id": str(order.id),
            "method": str(payment.method),
            "amount": str(to_money(row.amount, "refund")),
            "status": row.status,
            "external_reference": row.external_reference,
            "payment_status": payment.status,
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
        restock: bool | None = None,
        payments: object = None,
        refund: object = None,
        refund_method: str | None = None,
        refund_references: dict[str, str] | None = None,
        actor_user_id: UUID | None = None,
        shift_override: bool = False,
    ) -> dict:
        """The one-transaction exchange: returned goods, replacement sale, AND the difference.

        The return is a document against the original sale (capped at sold-minus-already-returned,
        priced at the original line price); the replacement is a new order priced off the CURRENT
        ladder. Both commit together under two receipts, paired by the return receipt id, and the
        exchange keeps the original order's customer.

        The money then moves, on the net:

        * **replacement costs more** — the difference is COLLECTED on the new order through the
          till's tender rules (``payments``), and the cash part goes into the drawer.
        * **replacement costs less** — the difference is REFUNDED across the tenders the original
          sale collected (``app.modules.pos.refund``), and the cash part comes out of the drawer.
        * **the same** — nothing moves, and the result says so (``settlement: exchange_only``)
          instead of leaving the cashier to guess.

        A till with ``pos.take_payments`` off moves no money and says ``record_only``. Whatever the
        sale never collected is reported as ``uncollected``, never paid out of the drawer."""
        from app.core.events.writer import add_outbox_event
        from app.modules.inventory.models import InventoryMovement
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
        await PosService._ensure_within_window(
            session,
            tenant_id,
            pos_session,
            receipt.issued_at,
            key="pos.exchange_max_days",
            fallback_key="pos.return_max_days",
            what="exchange",
        )
        restock = await PosService._resolve_restock(session, tenant_id, pos_session, restock)
        shelf = PosService._line_restock(return_lines, restock)
        reasons = await PosService._clean_return_reasons(
            session, tenant_id, pos_session, return_lines
        )
        conditions = PosService._return_conditions(return_lines)
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
        shelved = {v: q for v, q in requested.items() if shelf.get(v)}
        if shelved:
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
            for variant_id, quantity in shelved.items():
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
                "reason": reasons.get(variant_id),
                "condition": conditions.get(variant_id, "sellable"),
            }
            for variant_id, total in zip(requested, priced, strict=True)
        ]
        return_total = to_money(
            sum((e["refund_total"] for e in return_entries), Decimal("0")),
            "return_total",
        )
        # ---------- the new half: the original order's own customer ----------
        await PosService._ensure_cart_in_scope(session, tenant_id, pos_session, new_lines)
        # The replacement half takes line discounts like a sale, so it is held to the same ceiling.
        # Without this an exchange was a way round the owner's limit: return an item, take the
        # replacement at 100% off.
        await PosService._ensure_within_discount_ceiling(
            session,
            tenant_id,
            await PosService.resolve_profile(session, tenant_id, pos_session),
            new_lines,
            None,
            override=shift_override,
        )
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

        profile = await PosService.resolve_profile(session, tenant_id, pos_session)
        take_payments = bool(
            await PosService._setting(session, tenant_id, "pos.take_payments", pos_session)
        )
        net = to_money(new_grand_total - return_total, "net")
        tender_lines = parse_lines(payments)
        if not take_payments and (tender_lines or refund or refund_method):
            raise ValidationError(
                "this till does not record payments: turn on pos.take_payments "
                "or send no payments and no refund"
            )
        if take_payments and net > 0 and not tender_lines:
            raise ValidationError(
                f"the replacement costs {net} more than the return: "
                "collect the difference before completing the exchange"
            )

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

        # ---------- the money half: the net between the two invoice values ----------
        settlement: dict = {
            "mode": "exchange_only",
            "direction": "none",
            "amount": to_money(0, "amount"),
            "by_method": {},
            "slices": [],
            "awaiting_confirmation": [],
            "terminal_only": [],
        }
        if take_payments and net > 0:
            allowed = set(profile.allowed_payment_methods or []) if profile is not None else set()
            reference_required = [
                str(m)
                for m in (
                    await PosService._setting(
                        session, tenant_id, "pos.reference_required_methods", pos_session
                    )
                    or []
                )
            ]
            tender = settle(
                tender_lines,
                total=net,
                allowed_methods=allowed,
                reference_required=reference_required,
            )
            for line in tender.lines:
                await OrderService.add_payment(
                    session,
                    tenant_id,
                    new_order.id,
                    method=line.method,
                    amount=line.amount,
                    provider=line.reference,
                    actor_user_id=actor_user_id,
                )
            if tender.cash_kept > 0:
                session.add(
                    PosCashMovement(
                        tenant_id=tenant_id,
                        session_id=pos_session.id,
                        direction="in",
                        reason="cash_sale",
                        amount=tender.cash_kept,
                        reference_type="order",
                        reference_id=new_order.id,
                        notes="exchange difference collected"[:255],
                        created_by_user_id=actor_user_id,
                    )
                )
                await session.flush()
            settlement = {
                "mode": "tender",
                "direction": "collected",
                "amount": tender.paid,
                "by_method": dict(tender.by_method),
                "slices": [],
            }
        elif take_payments and net < 0:
            settlement = {
                **await PosService._settle_refund(
                    session,
                    tenant_id,
                    pos_session,
                    order,
                    -net,
                    requested=PosService._refund_request(refund),
                    single_method=refund_method,
                    reason="POS exchange: cheaper replacement",
                    actor_user_id=actor_user_id,
                    references=refund_references,
                ),
                "direction": "refunded",
                "amount": to_money(-net, "amount"),
            }

        if shelved:
            for entry in return_entries:
                if not shelf.get(entry["variant_id"]):
                    continue
                await PosService._restock_returned(
                    session,
                    tenant_id,
                    entry,
                    register.warehouse_id,
                    order_id=order_id,
                    actor_user_id=actor_user_id,
                )

        return_receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            order,
            number_prefix="POS-RET",
            kind="return",
            sold_by_user_id=actor_user_id,
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
                    reason=entry["reason"],
                    condition=entry["condition"],
                )
            )
        new_receipt = await PosService._issue_receipt(
            session,
            tenant_id,
            pos_session,
            new_order,
            exchange_return_receipt_id=return_receipt.id,  # the stored pairing
            sold_by_user_id=actor_user_id,
        )
        await session.flush()
        await PosService._issue_eta_receipt(session, tenant_id, pos_session, return_receipt)
        await PosService._issue_eta_receipt(session, tenant_id, pos_session, new_receipt)

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
                "settlement": settlement["direction"],
                "settled_amount": str(settlement["amount"]),
                "settled_by_method": {m: str(a) for m, a in settlement["by_method"].items()},
                "restocked": bool(shelved),
                "actor_user_id": str(actor_user_id) if actor_user_id else None,
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
            # The money: ``collected`` (the replacement cost more and the difference was taken),
            # ``refunded`` (it cost less and the difference went back), ``exchange_only`` (equal,
            # nothing moved) or ``record_only`` (a till that takes no payments).
            "settlement": (
                settlement["mode"] if settlement["direction"] == "none" else settlement["direction"]
            ),
            "settled_amount": str(settlement["amount"]),
            "settled_by_method": {m: str(a) for m, a in settlement["by_method"].items()},
            "uncollected": str(settlement.get("uncollected", "0.00")),
            # The card/wallet part of the difference is promised, not proven: the cashier
            # reverses it on the terminal and confirms it with the reference. `terminal_only` is
            # the same thing for a cash-only shop, which never records a non-cash reversal.
            "awaiting_confirmation": settlement.get("awaiting_confirmation", []),
            "terminal_only": settlement.get("terminal_only", []),
            "restocked": bool(shelved),
        }
