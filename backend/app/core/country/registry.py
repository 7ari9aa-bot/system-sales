"""Country registry — lookup and listing of all supported market profiles.

Designed so adding a new country is a matter of adding a profile file and
registering it here, without altering any business logic.
"""

from __future__ import annotations

from app.core.country.profiles.ae import AE
from app.core.country.profiles.eg import EG
from app.core.country.profiles.qa import QA
from app.core.country.profiles.sa import SA
from app.core.country.schema import CountrySpec

_PROFILES: tuple[CountrySpec, ...] = (EG, SA, AE, QA)

REGISTRY: dict[str, CountrySpec] = {country.code: country for country in _PROFILES}

SUPPORTED_COUNTRIES: tuple[str, ...] = tuple(sorted(REGISTRY.keys()))

DEFAULT_COUNTRY_CODE: str = "EG"


def get_country(code: str | None) -> CountrySpec | None:
    """Retrieve a country profile by its ISO 3166-1 alpha-2 code (case-insensitive)."""
    if not code:
        return None
    return REGISTRY.get(code.strip().upper())


def list_countries(*, include_hidden: bool = False) -> list[CountrySpec]:
    """Return all registered country profiles, optionally filtering out hidden ones."""
    if include_hidden:
        return list(_PROFILES)
    return [c for c in _PROFILES if c.launch_status != "hidden"]


def is_valid_country(code: str | None) -> bool:
    """True if the given code matches a registered country."""
    if not code:
        return False
    return code.strip().upper() in REGISTRY


def country_has_capability(
    code: str | None,
    capability: str,
    *,
    plan_features: dict | None = None,
) -> bool:
    """Check if a country supports a capability, optionally verified against plan features."""
    country = get_country(code)
    return country.has_capability(capability, plan_features=plan_features) if country else False


def country_refusal(code: str | None) -> str | None:
    """Validation refusal string for an unlisted country, or None if valid."""
    if not code or not code.strip():
        return f"country code is required; choose one of: {', '.join(SUPPORTED_COUNTRIES)}"
    clean = code.strip().upper()
    if clean not in REGISTRY:
        choices = ", ".join(SUPPORTED_COUNTRIES)
        return f"'{code}' is not a country this system operates in; choose one of: {choices}"
    return None
