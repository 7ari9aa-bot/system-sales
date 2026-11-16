"""Qatar market profile (QA)."""

from __future__ import annotations

from app.core.country.schema import CountrySpec

QA = CountrySpec(
    code="QA",
    name_ar="دولة قطر",
    name_en="Qatar",
    currency="QAR",
    currency_symbol_ar="ر.ق",
    currency_symbol_en="QAR",
    currency_decimals=2,
    default_timezone="Asia/Qatar",
    week_start="sunday",
    phone_code="974",
    phone_trunk_prefix="",
    phone_national_lengths=(8,),
    phone_national_regex=r"^[3567][0-9]{7}$",
    default_dialect="gulf",
    # Qatar currently operates without a general VAT regime in 2026.
    tax_regime="none",
    tax_standard_rate=None,
    tax_authority_name_ar="الهيئة العامة للضرائب",
    tax_authority_name_en="General Tax Authority",
    tax_inclusive_display=False,
    capabilities=frozenset(
        {
            "qatar_zones",
            "qpay_payments",
            "naps_debit",
        }
    ),
    launch_status="waitlist",
)
