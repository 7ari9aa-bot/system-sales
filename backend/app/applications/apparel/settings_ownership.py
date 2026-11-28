"""Which settings belong to the apparel application and which to the platform.

The settings registry holds every key in one place, and that is fine: one
registry, one validator, one history table. What must not happen is a single
undivided namespace where the platform's account screens and a shop's trading
rules are the same thing. This module draws the line, and a test proves the
line covers every domain the registry actually uses, so a new domain cannot
appear without somebody deciding who owns it (industry-applications §12).
"""

from __future__ import annotations

from app.applications.apparel.manifest import MODULES
from app.platform.settings.sector_boundary import PLATFORM_DOMAINS

#: Domains the platform owns: the account, its people, its security, its bill.
#: None of these describe how a shop trades, so no sector application may claim
#: them, and the platform screens may read them without knowing the sector.
#: Imported from the platform module rather than restated: the platform decides
#: what it owns, and the application only refuses to claim it.
PLATFORM_SETTINGS_DOMAINS: frozenset[str] = PLATFORM_DOMAINS

#: Domains that belong to the application as a whole rather than to one module:
#: what the business is, where it trades from, and how data comes in.
APP_LEVEL_SETTINGS_DOMAINS: frozenset[str] = frozenset(
    {
        "business",
        "branch",
        "imports",
    }
)


def owned_settings_domains() -> frozenset[str]:
    """Every settings domain FIHRIST Apparel owns, module-level and app-level."""
    module_domains = {domain for module in MODULES for domain in module.settings_domains}
    return frozenset(module_domains) | APP_LEVEL_SETTINGS_DOMAINS


def owner_of(domain: str) -> str | None:
    """``"platform"``, ``"apparel"``, or ``None`` when nobody claimed it."""
    if domain in PLATFORM_SETTINGS_DOMAINS:
        return "platform"
    if domain in owned_settings_domains():
        return "apparel"
    return None
