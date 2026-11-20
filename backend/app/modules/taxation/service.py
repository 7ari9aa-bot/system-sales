"""TAXATION service: the business profile and tax classes.

Validation lives here, not only in the database, so a refusal reads as a sentence the shop owner
can act on rather than a constraint name. The database CHECKs are the last line, not the first.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.taxation.models import VAT_STATUSES, BusinessProfile, TaxClass

# Arabic-Indic and Eastern Arabic-Indic digits -> ASCII, so a number typed on an Arabic keyboard
# is stored (and sent to the tax authority) in the one form it accepts.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# The three Egyptian treatments every shop starts with. 14% is the standard VAT rate.
DEFAULT_TAX_CLASSES: tuple[dict, ...] = (
    {
        "code": "VAT14",
        "name": "ضريبة القيمة المضافة 14%",
        "rate": Decimal("0.1400"),
        "eta_tax_type": "T1",
        "eta_sub_type": "V009",
        "is_default": True,
    },
    {
        "code": "ZERO",
        "name": "معفى بنسبة صفر",
        "rate": Decimal("0.0000"),
        "eta_tax_type": "T1",
        "eta_sub_type": "V001",
        "is_default": False,
    },
    {
        "code": "EXEMPT",
        "name": "معفى من الضريبة",
        "rate": Decimal("0.0000"),
        "eta_tax_type": "T1",
        "eta_sub_type": "V003",
        "is_default": False,
    },
)

_PROFILE_TEXT = (
    "trade_name",
    "commercial_register",
    "activity_code",
    "branch_code",
    "governorate",
    "city",
    "street",
    "building_number",
    "postal_code",
    "phone",
)


def normalise_tax_number(value: str | None) -> str | None:
    """Return the nine ASCII digits of an Egyptian tax registration number, or None if blank."""
    if value is None:
        return None
    cleaned = str(value).translate(_DIGITS).replace(" ", "").replace("-", "")
    if cleaned == "":
        return None
    if not (cleaned.isascii() and cleaned.isdigit() and len(cleaned) == 9):
        raise ValidationError("الرقم الضريبي لازم يكون 9 أرقام بالظبط")
    return cleaned


class TaxationService:
    # ------------------------------------------------------------ profile ----

    @staticmethod
    async def get_profile(session: AsyncSession, tenant_id: uuid.UUID) -> BusinessProfile | None:
        return (
            await session.execute(
                select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def upsert_profile(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        legal_name: str,
        vat_status: str = "not_registered",
        tax_registration_number: str | None = None,
        **optional: str | None,
    ) -> BusinessProfile:
        name = (legal_name or "").strip()
        if not name:
            raise ValidationError("اسم المنشأة مطلوب")
        if vat_status not in VAT_STATUSES:
            raise ValidationError("حالة التسجيل في ضريبة القيمة المضافة غير معروفة")
        number = normalise_tax_number(tax_registration_number)
        if vat_status == "registered" and number is None:
            raise ValidationError("المنشأة المسجلة في القيمة المضافة لازم يكون لها رقم ضريبي")
        unknown = set(optional) - set(_PROFILE_TEXT)
        if unknown:
            raise ValidationError(f"حقول غير معروفة: {', '.join(sorted(unknown))}")

        profile = await TaxationService.get_profile(session, tenant_id)
        if profile is None:
            profile = BusinessProfile(tenant_id=tenant_id, legal_name=name)
            session.add(profile)
        profile.legal_name = name
        profile.vat_status = vat_status
        profile.tax_registration_number = number
        for field in _PROFILE_TEXT:
            if field in optional:
                value = optional[field]
                setattr(profile, field, (value or "").strip() or None)
        if not profile.branch_code:
            profile.branch_code = "0"
        await session.flush()
        return profile

    @staticmethod
    def fiscal_readiness(profile: BusinessProfile | None) -> list[str]:
        """What is still missing before this business can lawfully issue an e-receipt."""
        if profile is None:
            return ["بيانات المنشأة لم تُدخل بعد"]
        missing: list[str] = []
        if not profile.tax_registration_number:
            missing.append("الرقم الضريبي")
        if not profile.activity_code:
            missing.append("كود النشاط")
        if not (profile.governorate and profile.city and profile.street):
            missing.append("العنوان (المحافظة والمدينة والشارع)")
        return missing

    # ------------------------------------------------------------ classes ----

    @staticmethod
    async def ensure_default_classes(session: AsyncSession, tenant_id: uuid.UUID) -> list[TaxClass]:
        existing = await TaxationService.list_classes(session, tenant_id, include_inactive=True)
        if existing:
            return existing
        for spec in DEFAULT_TAX_CLASSES:
            session.add(TaxClass(tenant_id=tenant_id, **spec))
        await session.flush()
        return await TaxationService.list_classes(session, tenant_id, include_inactive=True)

    @staticmethod
    async def list_classes(
        session: AsyncSession, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> list[TaxClass]:
        stmt = select(TaxClass).where(TaxClass.tenant_id == tenant_id).order_by(TaxClass.code)
        if not include_inactive:
            stmt = stmt.where(TaxClass.is_active.is_(True))
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def get_class(
        session: AsyncSession, tenant_id: uuid.UUID, class_id: uuid.UUID
    ) -> TaxClass:
        row = (
            await session.execute(
                select(TaxClass).where(TaxClass.tenant_id == tenant_id, TaxClass.id == class_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("فئة الضريبة غير موجودة")
        return row

    @staticmethod
    async def default_class(session: AsyncSession, tenant_id: uuid.UUID) -> TaxClass:
        rows = await TaxationService.ensure_default_classes(session, tenant_id)
        for row in rows:
            if row.is_default and row.is_active:
                return row
        raise ConflictError("لا توجد فئة ضريبة افتراضية")

    @staticmethod
    async def create_class(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        code: str,
        name: str,
        rate: str,
        eta_sub_type: str = "V009",
    ) -> TaxClass:
        await TaxationService.ensure_default_classes(session, tenant_id)
        code = (code or "").strip().upper()
        if not code or not name.strip():
            raise ValidationError("كود واسم الفئة مطلوبين")
        try:
            value = Decimal(str(rate).strip())
        except InvalidOperation as exc:
            raise ValidationError("نسبة الضريبة لازم تكون رقم") from exc
        if not (Decimal("0") <= value <= Decimal("1")):
            raise ValidationError("نسبة الضريبة كسر بين 0 و1 (14% = 0.14)")
        clash = await session.execute(
            select(TaxClass.id).where(TaxClass.tenant_id == tenant_id, TaxClass.code == code)
        )
        if clash.first() is not None:
            raise ConflictError("كود الفئة مستخدم قبل كده")
        row = TaxClass(
            tenant_id=tenant_id,
            code=code,
            name=name.strip(),
            rate=value.quantize(Decimal("0.0001")),
            eta_sub_type=eta_sub_type,
        )
        session.add(row)
        await session.flush()
        return row
