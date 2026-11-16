"""United Arab Emirates market profile (AE)."""

from __future__ import annotations

from app.core.country.schema import CountrySpec

AE = CountrySpec(
    code="AE",
    name_ar="الإمارات العربية المتحدة",
    name_en="United Arab Emirates",
    currency="AED",
    currency_symbol_ar="د.إ",
    currency_symbol_en="AED",
    currency_decimals=2,
    default_timezone="Asia/Dubai",
    week_start="sunday",
    phone_code="971",
    phone_trunk_prefix="0",
    phone_national_lengths=(9,),
    phone_national_regex=r"^0?5[0-9]{8}$",
    default_dialect="gulf",
    tax_regime="standard",
    tax_standard_rate=0.05,
    tax_authority_name_ar="الهيئة الاتحادية للضرائب",
    tax_authority_name_en="Federal Tax Authority",
    tax_inclusive_display=False,
    capabilities=frozenset(
        {
            "emirates_address",
            "tabby_bnpl",
            "tamara_bnpl",
            "apple_pay",
        }
    ),
    launch_status="waitlist",
    legal_urls={
        "terms": "/ae/ar/terms",
        "privacy": "/ae/ar/privacy",
        "contact_sales": "/ae/ar/contact-sales",
    },
)
