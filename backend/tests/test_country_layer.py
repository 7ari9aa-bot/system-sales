"""Unit tests for the Country & Market Layer (app.core.country).

Covers:
- CountrySpec model and attributes.
- Registry lookups, listing, filtering, and validation.
- Phone normalization for Egypt, Saudi Arabia, UAE, and Qatar.
- Country capabilities and tax regimes.
"""

from __future__ import annotations

import pytest

from app.core.contact_norm import ContactNormalizationError, normalize_phone
from app.core.country import (
    DEFAULT_COUNTRY_CODE,
    SUPPORTED_COUNTRIES,
    country_has_capability,
    country_refusal,
    get_country,
    is_valid_country,
    list_countries,
)


def test_registry_contains_initial_four_countries():
    assert set(SUPPORTED_COUNTRIES) == {"AE", "EG", "QA", "SA"}
    assert DEFAULT_COUNTRY_CODE == "EG"


def test_country_lookup_case_insensitive():
    eg = get_country("eg")
    assert eg is not None
    assert eg.code == "EG"
    assert eg.name_ar == "مصر"
    assert eg.currency == "EGP"
    assert eg.default_timezone == "Africa/Cairo"
    assert eg.week_start == "saturday"
    assert eg.tax_regime == "standard"
    assert eg.tax_standard_rate == 0.14
    assert eg.launch_status == "live"


def test_saudi_spec():
    sa = get_country("SA")
    assert sa is not None
    assert sa.currency == "SAR"
    assert sa.default_timezone == "Asia/Riyadh"
    assert sa.week_start == "sunday"
    assert sa.tax_regime == "standard"
    assert sa.tax_standard_rate == 0.15
    assert sa.phone_code == "966"
    assert sa.has_capability("national_address")
    assert sa.has_capability("mada_payments")
    assert not sa.has_capability("fawry_payments")
    assert sa.launch_status == "live"


def test_qatar_no_vat_regime():
    qa = get_country("QA")
    assert qa is not None
    assert qa.tax_regime == "none"
    assert qa.tax_standard_rate is None
    assert qa.currency == "QAR"
    assert qa.launch_status == "waitlist"


def test_uae_spec():
    ae = get_country("AE")
    assert ae is not None
    assert ae.currency == "AED"
    assert ae.tax_standard_rate == 0.05
    assert ae.launch_status == "waitlist"


def test_country_refusal():
    assert is_valid_country("EG")
    assert is_valid_country("sa")
    assert not is_valid_country("US")
    assert not is_valid_country("")
    assert country_refusal("EG") is None
    assert country_refusal("SA") is None
    assert "not a country this system operates in" in (country_refusal("US") or "")
    assert "country code is required" in (country_refusal("") or "")


def test_country_capabilities():
    assert country_has_capability("EG", "instapay_reference")
    assert not country_has_capability("SA", "instapay_reference")
    assert country_has_capability("SA", "mada_payments")
    assert not country_has_capability("EG", "mada_payments")


def test_list_countries_filter_hidden():
    live_and_waitlist = list_countries(include_hidden=False)
    assert len(live_and_waitlist) == 4


def test_phone_normalization_egypt():
    # National 10-digit mobile with trunk '0'
    assert normalize_phone("01001234567", default_country_code="EG") == "+201001234567"
    # National without trunk
    assert normalize_phone("1001234567", default_country_code="20") == "+201001234567"
    # International form
    assert normalize_phone("+201001234567") == "+201001234567"


def test_phone_normalization_saudi():
    # 9-digit mobile with trunk '0'
    assert normalize_phone("0501234567", default_country_code="SA") == "+966501234567"
    # 9-digit mobile without trunk
    assert normalize_phone("501234567", default_country_code="966") == "+966501234567"
    # International format
    assert normalize_phone("+966501234567") == "+966501234567"
    # Invalid length for Saudi
    with pytest.raises(ContactNormalizationError):
        normalize_phone("05012345", default_country_code="SA")


def test_phone_normalization_uae():
    # 9-digit mobile with trunk '0'
    assert normalize_phone("0501234567", default_country_code="AE") == "+971501234567"
    assert normalize_phone("501234567", default_country_code="971") == "+971501234567"


def test_phone_normalization_qatar():
    # 8-digit mobile without trunk
    assert normalize_phone("55123456", default_country_code="QA") == "+97455123456"
    assert normalize_phone("+97455123456") == "+97455123456"
