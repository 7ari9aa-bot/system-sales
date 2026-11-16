"""Public markets endpoint — read-only market configuration and plan pricing for the marketing site.

No auth, no tenant context, no RLS — queries global catalog tables (plans, plan_prices)
and core CountrySpec facts. Cached for fast edge responses on Vercel.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.core.country import get_country
from app.modules.billing.models import Plan, PlanPrice
from app.modules.identity.deps import DbSession

router = APIRouter(tags=["markets"])


class PlanPriceOut(BaseModel):
    interval: str  # month | year
    price: float
    currency: str


class PublicPlanOut(BaseModel):
    code: str
    name: str
    features: dict[str, Any]
    prices: list[PlanPriceOut]


class PaymentMethodInfo(BaseModel):
    key: str
    name_ar: str
    name_en: str


class ShippingCarrierInfo(BaseModel):
    key: str
    name_ar: str
    name_en: str


class SupportInfo(BaseModel):
    email: str
    contact_sales_url: str
    terms_url: str
    privacy_url: str


class PublicMarketOut(BaseModel):
    code: str
    name_ar: str
    name_en: str
    currency: str
    currency_symbol_ar: str
    currency_symbol_en: str
    currency_decimals: int
    default_timezone: str
    week_start: str
    phone_code: str
    default_dialect: str
    tax_regime: str
    tax_standard_rate: float | None
    tax_authority_name_ar: str | None
    tax_authority_name_en: str | None
    tax_inclusive_display: bool
    capabilities: list[str]
    launch_status: str
    plans: list[PublicPlanOut]
    payment_methods: list[PaymentMethodInfo]
    shipping_carriers: list[ShippingCarrierInfo]
    support: SupportInfo


_VERIFIED_PAYMENT_METHODS: dict[str, list[dict[str, str]]] = {
    "EG": [
        {"key": "instapay", "name_ar": "إنستاباي", "name_en": "InstaPay"},
        {"key": "fawry", "name_ar": "فوري", "name_en": "Fawry"},
        {
            "key": "vodafone_cash",
            "name_ar": "فودافون كاش ومحافظ المحمول",
            "name_en": "Mobile Wallets",
        },
        {"key": "cod", "name_ar": "الدفع عند الاستلام", "name_en": "Cash on Delivery"},
    ],
    "SA": [
        {"key": "mada", "name_ar": "مدى", "name_en": "Mada"},
        {"key": "stc_pay", "name_ar": "STC Pay", "name_en": "STC Pay"},
        {"key": "tamara", "name_ar": "تمارا", "name_en": "Tamara"},
        {"key": "tabby", "name_ar": "تابي", "name_en": "Tabby"},
        {"key": "bank_transfer", "name_ar": "تحويل بنكي مباشر", "name_en": "Bank Transfer"},
    ],
    "AE": [
        {"key": "apple_pay", "name_ar": "أبل باي", "name_en": "Apple Pay"},
        {"key": "card", "name_ar": "بطاقة بنكية", "name_en": "Credit/Debit Card"},
        {"key": "tabby", "name_ar": "تابي", "name_en": "Tabby"},
    ],
    "QA": [
        {"key": "qpay", "name_ar": "بوابة كيو باي", "name_en": "QPay"},
        {"key": "naps", "name_ar": "بطاقات نافس الوطنية", "name_en": "NAPS Debit"},
        {"key": "card", "name_ar": "بطاقة بنكية", "name_en": "Credit/Debit Card"},
    ],
}

_VERIFIED_SHIPPING_CARRIERS: dict[str, list[dict[str, str]]] = {
    "EG": [{"key": "bosta", "name_ar": "بوسطة", "name_en": "Bosta"}],
    "SA": [{"key": "smsa", "name_ar": "سمسا إكسبريس", "name_en": "SMSA Express"}],
    "AE": [{"key": "aramex", "name_ar": "أرامكس", "name_en": "Aramex"}],
    "QA": [{"key": "qpost", "name_ar": "بريد قطر", "name_en": "Qatar Post"}],
}


@router.get("/public/markets/{country}", response_model=PublicMarketOut)
async def get_public_market(
    country: str,
    session: DbSession,
    response: Response,
) -> PublicMarketOut:
    """Retrieve public market specifications, plans and pricing for the marketing site."""
    code = (country or "").strip().upper()
    spec = get_country(code)
    if spec is None or spec.launch_status == "hidden":
        raise HTTPException(status_code=404, detail=f"Market '{country}' not found")

    # Edge caching: 5 minutes browser cache, 1 hour CDN cache, 24 hours stale-while-revalidate
    response.headers["Cache-Control"] = (
        "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"
    )

    # Try querying plans and prices from DB; if DB is unavailable, gracefully fall back
    # to standard plan catalog so the public marketing site never errors (500).
    public_plans: list[PublicPlanOut] = []
    try:
        plans_stmt = select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price.asc())
        plans_result = (await session.execute(plans_stmt)).scalars().all()

        prices_stmt = select(PlanPrice).where(
            PlanPrice.country_code == code,
            PlanPrice.is_active.is_(True),
        )
        prices_result = (await session.execute(prices_stmt)).scalars().all()
        prices_by_plan: dict[Any, list[PlanPriceOut]] = {}
        for p in prices_result:
            prices_by_plan.setdefault(p.plan_id, []).append(
                PlanPriceOut(interval=p.interval, price=float(p.price), currency=p.currency)
            )

        for plan in plans_result:
            matched_prices = prices_by_plan.get(plan.id)
            if not matched_prices:
                matched_prices = [
                    PlanPriceOut(
                        interval=plan.interval or "month",
                        price=float(plan.price),
                        currency=plan.currency or spec.currency,
                    )
                ]
            public_plans.append(
                PublicPlanOut(
                    code=plan.code,
                    name=plan.name,
                    features=plan.features or {},
                    prices=matched_prices,
                )
            )
    except Exception:
        # Fallback catalog when database is unreachable
        ratio = 0.08 if spec.currency != "EGP" else 1.0
        fallback_catalog = [
            ("starter", "Starter", 0.0, {"max_users": 3, "ai_agents": 1}),
            ("basic", "Basic", round(590.0 * ratio, 2), {"max_users": 5, "ai_agents": 1}),
            ("pro", "Pro", round(1500.0 * ratio, 2), {"max_users": 15, "ai_agents": 10}),
            ("business", "Business", round(3500.0 * ratio, 2), {"max_users": 40, "ai_agents": 25}),
            ("enterprise", "Enterprise", 0.0, {"max_users": 100, "ai_agents": 100}),
        ]
        public_plans = [
            PublicPlanOut(
                code=code_p,
                name=name_p,
                features=feats,
                prices=[PlanPriceOut(interval="month", price=pr, currency=spec.currency)],
            )
            for code_p, name_p, pr, feats in fallback_catalog
        ]

    return PublicMarketOut(
        code=spec.code,
        name_ar=spec.name_ar,
        name_en=spec.name_en,
        currency=spec.currency,
        currency_symbol_ar=spec.currency_symbol_ar,
        currency_symbol_en=spec.currency_symbol_en,
        currency_decimals=spec.currency_decimals,
        default_timezone=spec.default_timezone,
        week_start=spec.week_start,
        phone_code=f"+{spec.phone_code}",
        default_dialect=spec.default_dialect,
        tax_regime=spec.tax_regime,
        tax_standard_rate=spec.tax_standard_rate,
        tax_authority_name_ar=spec.tax_authority_name_ar,
        tax_authority_name_en=spec.tax_authority_name_en,
        tax_inclusive_display=spec.tax_inclusive_display,
        capabilities=sorted(spec.capabilities),
        launch_status=spec.launch_status,
        plans=public_plans,
        payment_methods=[PaymentMethodInfo(**m) for m in _VERIFIED_PAYMENT_METHODS.get(code, [])],
        shipping_carriers=[
            ShippingCarrierInfo(**s) for s in _VERIFIED_SHIPPING_CARRIERS.get(code, [])
        ],
        support=SupportInfo(
            email="support@fihrist.world",
            contact_sales_url=f"/{code.lower()}/ar/contact-sales",
            terms_url=f"/{code.lower()}/ar/terms",
            privacy_url=f"/{code.lower()}/ar/privacy",
        ),
    )
