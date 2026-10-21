"""POS profile service — the terminal configuration (§189 expansion).

A profile is the ERPNext `POS Profile` idea on our stack: one place that says
which warehouse a terminal sells from, who the walk-in customer is, which
payment methods it accepts, and how large a discount a cashier may give without
a second pair of eyes. It owns configuration and the access grants only — it
never touches a sale, an order, or a ledger.

Services are flush-only; the caller owns the transaction (§186).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.orders.money import to_money
from app.modules.pos.models import PosProfile, PosProfileUser, PosRegister, PosSession

#: The closed payment vocabulary — must match ``orders/service._PAYMENT_METHODS``.
PAYMENT_METHODS = ("cash", "card", "wallet", "bank_transfer")


def _clean_code(code: object) -> str:
    cleaned = str(code).strip()
    if not cleaned or len(cleaned) > 31:
        raise ValidationError("profile code must be 1-31 characters")
    return cleaned


class ApprovalRequiredError(ValidationError):
    """The action is above the cashier's own limit and a manager must approve it.

    Still a 400 and still a ``ValidationError`` (nothing that catches those changes), but with a
    stable ``code`` so the till can open the manager-PIN dialog instead of showing a red message.
    ``details`` says which limit was crossed: ``{"limit": "refund" | "cash_out" | "discount",
    "ceiling": "<amount>"}``.
    """

    code = "approval_required"
    expose_details = True  # {"limit", "ceiling"}: written for the till, nothing internal


def _clean_ceiling(value: object) -> Decimal:
    """A discount ceiling is a percentage in [0, 100], quantized to 2 places."""
    ceiling = to_money(value, "discount_ceiling_pct")
    if ceiling < 0 or ceiling > 100:
        raise ValidationError("discount_ceiling_pct must be between 0 and 100")
    return ceiling


#: "the caller did not send this field" - distinct from None, which means "remove the limit".
_UNSET: object = object()


def _clean_money_ceiling(value: object, field: str) -> Decimal | None:
    """A money ceiling: None/blank = no limit, otherwise a non-negative amount (2 places)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    ceiling = to_money(value, field)
    if ceiling < 0:
        raise ValidationError(f"{field} cannot be negative")
    return ceiling


def _clean_methods(methods: object) -> list[str]:
    if methods is None:
        return list(PAYMENT_METHODS)
    if not isinstance(methods, (list, tuple)) or not methods:
        raise ValidationError("allowed_payment_methods must be a non-empty list")
    unknown = [m for m in methods if m not in PAYMENT_METHODS]
    if unknown:
        raise ValidationError(
            f"unknown payment methods {sorted(set(unknown))}; allowed {sorted(PAYMENT_METHODS)}"
        )
    # Deduplicate while preserving the caller's order.
    seen: list[str] = []
    for method in methods:
        if method not in seen:
            seen.append(method)
    return seen


def _clean_default_method(value: object) -> str | None:
    """The till's preselected tender — a member of the closed vocabulary."""
    if value is None:
        return None
    method = str(value)
    if method not in PAYMENT_METHODS:
        raise ValidationError(f"default_payment_method must be one of {sorted(PAYMENT_METHODS)}")
    return method


def _clean_return_methods(value: object) -> list[str]:
    """Methods a refund may travel through (ERPNext `allow_in_returns`)."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError("returns_allowed_methods must be a list")
    cleaned: list[str] = []
    for raw in value:
        method = str(raw)
        if method not in PAYMENT_METHODS:
            raise ValidationError(
                f"unknown refund method {method!r}; allowed {sorted(PAYMENT_METHODS)}"
            )
        if method not in cleaned:
            cleaned.append(method)
    return cleaned


def _clean_item_groups(value: object) -> list[str]:
    """Category ids this terminal serves (ERPNext `POS Item Group`); empty
    list = the tenant's whole catalog."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError("item_group_ids must be a list")
    cleaned: list[str] = []
    for raw in value:
        try:
            group_id = str(UUID(str(raw)))
        except ValueError:
            raise ValidationError("each item_group_ids entry must be a UUID") from None
        if group_id not in cleaned:
            cleaned.append(group_id)
    return cleaned


class PosProfileService:
    """Profile CRUD, access grants, and the discount-ceiling policy."""

    # ------------------------------------------------------------ CRUD ----

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        code: str,
        warehouse_id: UUID,
        default_customer_id: UUID | None = None,
        allowed_payment_methods: object = None,
        discount_ceiling_pct: object = "0",
        require_customer: bool = False,
        default_payment_method: object = None,
        returns_allowed_methods: object = None,
        item_group_ids: object = None,
        refund_ceiling: object = None,
        cash_out_ceiling: object = None,
    ) -> PosProfile:
        from app.modules.customers.service import CustomerService
        from app.modules.inventory.service import InventoryService

        cleaned_code = _clean_code(code)
        # Fail with a sentence before the unique index does (§189 discipline).
        await InventoryService.get_warehouse(session, tenant_id, warehouse_id)
        if default_customer_id is not None:
            # Refuses a tombstoned/merged customer — never a fake id.
            await CustomerService.get(session, tenant_id, default_customer_id)

        cleaned_groups = _clean_item_groups(item_group_ids)
        if cleaned_groups:
            await PosProfileService._ensure_categories_exist(session, tenant_id, cleaned_groups)

        profile = PosProfile(
            tenant_id=tenant_id,
            name=str(name).strip() or cleaned_code,
            code=cleaned_code,
            warehouse_id=warehouse_id,
            default_customer_id=default_customer_id,
            allowed_payment_methods=_clean_methods(allowed_payment_methods),
            discount_ceiling_pct=_clean_ceiling(discount_ceiling_pct),
            require_customer=bool(require_customer),
            refund_ceiling=_clean_money_ceiling(refund_ceiling, "refund_ceiling"),
            cash_out_ceiling=_clean_money_ceiling(cash_out_ceiling, "cash_out_ceiling"),
            default_payment_method=_clean_default_method(default_payment_method),
            returns_allowed_methods=_clean_return_methods(returns_allowed_methods),
            item_group_ids=cleaned_groups,
        )
        session.add(profile)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"profile code '{cleaned_code}' already exists") from None
        return profile

    @staticmethod
    async def list_profiles(session: AsyncSession, tenant_id: UUID) -> list[PosProfile]:
        rows = (
            (
                await session.execute(
                    select(PosProfile)
                    .where(PosProfile.tenant_id == tenant_id)
                    .order_by(PosProfile.created_at.asc(), PosProfile.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, profile_id: UUID) -> PosProfile:
        profile = (
            await session.execute(
                select(PosProfile).where(
                    PosProfile.tenant_id == tenant_id,
                    PosProfile.id == profile_id,
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise NotFoundError(f"pos profile {profile_id} not found")
        return profile

    @staticmethod
    async def update(
        session: AsyncSession,
        tenant_id: UUID,
        profile_id: UUID,
        *,
        name: str | None = None,
        warehouse_id: UUID | None = None,
        default_customer_id: UUID | None = None,
        allowed_payment_methods: object = None,
        discount_ceiling_pct: object = None,
        require_customer: bool | None = None,
        is_active: bool | None = None,
        default_payment_method: object = None,
        returns_allowed_methods: object = None,
        item_group_ids: object = None,
        refund_ceiling: object = _UNSET,
        cash_out_ceiling: object = _UNSET,
    ) -> PosProfile:
        from app.modules.customers.service import CustomerService
        from app.modules.inventory.service import InventoryService

        profile = await PosProfileService.get(session, tenant_id, profile_id)
        if name is not None:
            cleaned = str(name).strip()
            if not cleaned:
                raise ValidationError("name must not be blank")
            profile.name = cleaned
        if warehouse_id is not None:
            await InventoryService.get_warehouse(session, tenant_id, warehouse_id)
            # The till's own warehouse is what a sale draws from, so a profile cannot quietly
            # point somewhere else: moving a till's stock pool is a decision about that till.
            stranded = (
                await session.execute(
                    select(func.count())
                    .select_from(PosRegister)
                    .where(
                        PosRegister.tenant_id == tenant_id,
                        PosRegister.profile_id == profile.id,
                        PosRegister.warehouse_id != warehouse_id,
                    )
                )
            ).scalar_one()
            if stranded:
                raise ConflictError(
                    f"{stranded} register(s) on this profile sell from a different warehouse; "
                    "move or detach them first"
                )
            profile.warehouse_id = warehouse_id
        if default_customer_id is not None:
            await CustomerService.get(session, tenant_id, default_customer_id)
            profile.default_customer_id = default_customer_id
        if allowed_payment_methods is not None:
            profile.allowed_payment_methods = _clean_methods(allowed_payment_methods)
        if discount_ceiling_pct is not None:
            profile.discount_ceiling_pct = _clean_ceiling(discount_ceiling_pct)
        if require_customer is not None:
            profile.require_customer = bool(require_customer)
        if refund_ceiling is not _UNSET:
            profile.refund_ceiling = _clean_money_ceiling(refund_ceiling, "refund_ceiling")
        if cash_out_ceiling is not _UNSET:
            profile.cash_out_ceiling = _clean_money_ceiling(cash_out_ceiling, "cash_out_ceiling")
        if default_payment_method is not None:
            profile.default_payment_method = _clean_default_method(default_payment_method)
        if returns_allowed_methods is not None:
            profile.returns_allowed_methods = _clean_return_methods(returns_allowed_methods)
        if item_group_ids is not None:
            cleaned_groups = _clean_item_groups(item_group_ids)
            if cleaned_groups:
                await PosProfileService._ensure_categories_exist(session, tenant_id, cleaned_groups)
            profile.item_group_ids = cleaned_groups
        if is_active is not None:
            if not bool(is_active) and profile.is_active:
                # ERPNext `validate_disabled`: a terminal with a live shift
                # cannot be switched off from under the cashier holding it.
                open_session = (
                    await session.execute(
                        select(PosSession.id).where(
                            PosSession.tenant_id == tenant_id,
                            PosSession.profile_id == profile.id,
                            PosSession.status == "OPEN",
                        )
                    )
                ).scalar_one_or_none()
                if open_session is not None:
                    raise ConflictError(
                        "this profile has an open session; close it before disabling"
                    )
            profile.is_active = bool(is_active)
        await session.flush()
        return profile

    # --------------------------------------------------------- access -----

    @staticmethod
    async def grant_user(
        session: AsyncSession, tenant_id: UUID, profile_id: UUID, user_id: UUID
    ) -> PosProfileUser:
        await PosProfileService.get(session, tenant_id, profile_id)
        row = PosProfileUser(tenant_id=tenant_id, profile_id=profile_id, user_id=user_id)
        session.add(row)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError("this user already operates this profile") from None
        return row

    @staticmethod
    async def revoke_user(
        session: AsyncSession, tenant_id: UUID, profile_id: UUID, user_id: UUID
    ) -> None:
        row = (
            await session.execute(
                select(PosProfileUser).where(
                    PosProfileUser.tenant_id == tenant_id,
                    PosProfileUser.profile_id == profile_id,
                    PosProfileUser.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("this user does not operate this profile")
        await session.delete(row)

    @staticmethod
    async def list_users(
        session: AsyncSession, tenant_id: UUID, profile_id: UUID
    ) -> list[PosProfileUser]:
        rows = (
            (
                await session.execute(
                    select(PosProfileUser)
                    .where(
                        PosProfileUser.tenant_id == tenant_id,
                        PosProfileUser.profile_id == profile_id,
                    )
                    .order_by(PosProfileUser.created_at.asc(), PosProfileUser.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def can_operate(
        session: AsyncSession, tenant_id: UUID, profile_id: UUID, user_id: UUID
    ) -> bool:
        """A predicate that returns, never raises (AGENT_BRIEF §6).

        A profile with NO grants is open to any ``orders:write`` holder — the
        router's permission gate is the only gate for an ungranted profile. The
        moment one user is granted, the profile is restricted to its grantees.
        """
        granted = (
            await session.execute(
                select(func.count())
                .select_from(PosProfileUser)
                .where(
                    PosProfileUser.tenant_id == tenant_id,
                    PosProfileUser.profile_id == profile_id,
                )
            )
        ).scalar_one()
        if granted == 0:
            return True
        return (
            await session.execute(
                select(PosProfileUser.id).where(
                    PosProfileUser.tenant_id == tenant_id,
                    PosProfileUser.profile_id == profile_id,
                    PosProfileUser.user_id == user_id,
                )
            )
        ).scalar_one_or_none() is not None

    @staticmethod
    async def _ensure_categories_exist(
        session: AsyncSession, tenant_id: UUID, group_ids: list[str]
    ) -> None:
        """A scoped terminal pointing at a missing category would silently
        serve an empty catalog — refuse the id, never the sale. The check
        rides the catalog's own service, never its tables."""
        from app.modules.catalog.service import CatalogService

        ok = await CatalogService.categories_exist(session, tenant_id, [UUID(g) for g in group_ids])
        if not ok:
            raise ValidationError("item_group_ids contains a category this tenant does not have")

    # --------------------------------------------------------- policy -----

    @staticmethod
    def discount_needs_approval(
        profile: PosProfile, discount_total: object, subtotal: object
    ) -> bool:
        """Whether a discount exceeds the profile's ceiling (pure, no session).

        The ceiling is a percentage of the cart subtotal. A ceiling of 0 means
        every discount needs approval — the safe default.
        """
        sub = to_money(subtotal, "subtotal")
        if sub <= 0:
            return False
        discount = to_money(discount_total or "0", "discount_total")
        if discount <= 0:
            return False
        pct = (discount / sub * Decimal("100")).quantize(Decimal("0.01"))
        return pct > to_money(profile.discount_ceiling_pct, "discount_ceiling_pct")

    @staticmethod
    def ensure_discount_allowed(
        profile: PosProfile,
        discount_total: object,
        subtotal: object,
        *,
        approved: bool,
    ) -> None:
        """The raising half of the pair: refuse an unapproved over-ceiling discount."""
        if approved:
            return
        if PosProfileService.discount_needs_approval(profile, discount_total, subtotal):
            raise ApprovalRequiredError(
                f"discount exceeds this profile's ceiling of "
                f"{profile.discount_ceiling_pct}% and needs an approval",
                details={"limit": "discount", "ceiling": str(profile.discount_ceiling_pct)},
            )

    @staticmethod
    def ensure_within_money_ceiling(
        profile: PosProfile | None,
        amount: object,
        *,
        kind: str,
        approved: bool,
    ) -> None:
        """Refuse a return or a cash pay-out above the profile's ceiling unless a manager approved.

        ``kind`` is ``"refund"`` or ``"cash_out"``. No profile, or a NULL ceiling, means the owner
        set no limit: nothing is refused. An amount equal to the ceiling passes; only more needs
        a manager.
        """
        if approved or profile is None:
            return
        ceiling = profile.refund_ceiling if kind == "refund" else profile.cash_out_ceiling
        if ceiling is None:
            return
        if to_money(amount, "amount") > to_money(ceiling, "ceiling"):
            what = "a return" if kind == "refund" else "cash out of the drawer"
            raise ApprovalRequiredError(
                f"{what} above {ceiling} needs a manager's approval on this till",
                details={"limit": kind, "ceiling": str(ceiling)},
            )
