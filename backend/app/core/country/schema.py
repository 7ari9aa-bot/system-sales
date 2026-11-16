"""Country specification data model — the single source of truth for market facts.

Stdlib-only: this is imported across the core and domain modules, so it must
never drag in FastAPI, database sessions, or third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LaunchStatus = Literal["live", "waitlist", "hidden"]
TaxRegime = Literal["standard", "none"]


@dataclass(frozen=True)
class CountrySpec:
    """The immutable specification of a supported country/market."""

    code: str  # ISO 3166-1 alpha-2, e.g. "EG", "SA", "AE", "QA"
    name_ar: str
    name_en: str
    currency: str  # ISO 4217, e.g. "EGP", "SAR", "AED", "QAR"
    currency_symbol_ar: str
    currency_symbol_en: str
    currency_decimals: int
    default_timezone: str  # IANA timezone, e.g. "Africa/Cairo"
    week_start: Literal["saturday", "sunday", "monday"]
    phone_code: str  # Country calling code without '+', e.g. "20", "966"
    phone_trunk_prefix: str  # e.g. "0"
    phone_national_lengths: tuple[int, ...]  # Allowed length(s) without country prefix
    phone_national_regex: str  # Validation pattern for national portion
    default_dialect: str  # e.g. "egyptian", "gulf"
    tax_regime: TaxRegime  # "standard" | "none" (Qatar is none, EG/SA/AE are standard)
    tax_standard_rate: float | None  # e.g. 0.14 for EG, 0.15 for SA, 0.05 for AE, None for QA
    tax_authority_name_ar: str | None
    tax_authority_name_en: str | None
    tax_inclusive_display: bool  # False = prices are quoted pre-tax
    capabilities: frozenset[str] = field(default_factory=frozenset)
    launch_status: LaunchStatus = "live"
    legal_urls: dict[str, str] = field(default_factory=dict)

    def has_capability(self, capability: str, *, plan_features: dict | None = None) -> bool:
        """Check if this market supports a feature/gateway, optionally gated by plan."""
        if capability not in self.capabilities:
            return False
        if plan_features is None:
            return True
        if plan_features.get("custom") is True:
            return True
        if capability in plan_features:
            return bool(plan_features[capability])
        allowed = plan_features.get("capabilities") or plan_features.get("allowed_capabilities")
        if allowed is not None:
            if isinstance(allowed, (list, tuple, set, frozenset)):
                return capability in allowed or "*" in allowed
            return bool(allowed)
        return True

    def to_public_dict(self) -> dict:
        """Serialize for the public marketing API and client consumers."""
        return {
            "code": self.code,
            "name_ar": self.name_ar,
            "name_en": self.name_en,
            "currency": self.currency,
            "currency_symbol_ar": self.currency_symbol_ar,
            "currency_symbol_en": self.currency_symbol_en,
            "currency_decimals": self.currency_decimals,
            "default_timezone": self.default_timezone,
            "week_start": self.week_start,
            "phone_code": f"+{self.phone_code}",
            "default_dialect": self.default_dialect,
            "tax_regime": self.tax_regime,
            "tax_standard_rate": self.tax_standard_rate,
            "tax_authority_name_ar": self.tax_authority_name_ar,
            "tax_authority_name_en": self.tax_authority_name_en,
            "tax_inclusive_display": self.tax_inclusive_display,
            "capabilities": sorted(self.capabilities),
            "launch_status": self.launch_status,
            "legal_urls": dict(self.legal_urls),
        }
