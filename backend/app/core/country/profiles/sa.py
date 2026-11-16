"""Saudi Arabia market profile (SA)."""

from __future__ import annotations

from app.core.country.schema import CountrySpec

SA = CountrySpec(
    code="SA",
    name_ar="المملكة العربية السعودية",
    name_en="Saudi Arabia",
    currency="SAR",
    currency_symbol_ar="ر.س",
    currency_symbol_en="SAR",
    currency_decimals=2,
    default_timezone="Asia/Riyadh",
    week_start="sunday",
    phone_code="966",
    phone_trunk_prefix="0",
    phone_national_lengths=(9,),
    phone_national_regex=r"^0?5[0-9]{8}$",
    default_dialect="gulf",
    tax_regime="standard",
    tax_standard_rate=0.15,
    tax_authority_name_ar="هيئة الزكاة والضريبة والجمارك",
    tax_authority_name_en="Zakat, Tax and Customs Authority (ZATCA)",
    tax_inclusive_display=False,
    capabilities=frozenset(
        {
            "national_address",
            "mada_payments",
            "stc_pay",
            "tamara_bnpl",
            "tabby_bnpl",
            "smsa_shipping",
        }
    ),
    launch_status="live",
    legal_urls={
        "terms": "/sa/ar/terms",
        "privacy": "/sa/ar/privacy",
        "contact_sales": "/sa/ar/contact-sales",
    },
)
