"""Egypt market profile (EG)."""

from __future__ import annotations

from app.core.country.schema import CountrySpec

EG = CountrySpec(
    code="EG",
    name_ar="مصر",
    name_en="Egypt",
    currency="EGP",
    currency_symbol_ar="ج.م",
    currency_symbol_en="EGP",
    currency_decimals=2,
    default_timezone="Africa/Cairo",
    week_start="saturday",
    phone_code="20",
    phone_trunk_prefix="0",
    phone_national_lengths=(9, 10),
    phone_national_regex=r"^0?1[0125][0-9]{8}$",
    default_dialect="egyptian",
    tax_regime="standard",
    tax_standard_rate=0.14,
    tax_authority_name_ar="مصلحة الضرائب المصرية",
    tax_authority_name_en="Egyptian Tax Authority",
    tax_inclusive_display=False,
    capabilities=frozenset(
        {
            "governorate_address",
            "instapay_reference",
            "fawry_payments",
            "vodafone_cash",
            "bosta_shipping",
        }
    ),
    launch_status="live",
    legal_urls={
        "terms": "/eg/ar/terms",
        "privacy": "/eg/ar/privacy",
        "contact_sales": "/eg/ar/contact-sales",
    },
)
