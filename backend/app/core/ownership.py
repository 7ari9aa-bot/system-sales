"""Which module belongs to which layer of the platform.

The platform is two layers, and the difference is ownership, not deployment:
``platform`` runs accounts, licences and operations and must not know how a
sector trades; an application owns a sector's rules, data and screens.

This file is the single place that decides which module sits where, so a test
can enforce the rule instead of a document asking politely. Adding a module
without classifying it here fails the boundary test: an unclassified module
would otherwise be silently exempt from every rule.

The one direction that is always allowed is application -> platform. An
application uses identity, billing and the request context. The reverse is the
leak this layer exists to prevent.
"""

from __future__ import annotations

#: Modules that run the platform: accounts, access, licences, operations,
#: storage, jobs, observability. None of them may read sector business data.
PLATFORM_MODULES: frozenset[str] = frozenset(
    {
        "activity",
        "applications",
        "authority",
        "automation",
        "billing",
        "decisions",
        "effects",
        "events",
        "evidence",
        "identity",
        "imports",
        "notifications",
        "operations",
        "platform",
        "privacy",
        "realtime",
        "voice",
    }
)

#: Modules owned by the apparel application: a sector's rules, data and screens.
APPAREL_MODULES: frozenset[str] = frozenset(
    {
        "ai",
        "analytics",
        "catalog",
        "conversations",
        "customer_accounts",
        "customers",
        "einvoice",
        "expenses",
        "financial",
        "inventory",
        "marketing",
        "orders",
        "pos",
        "pricing",
        "purchasing",
        "segments",
        "settings",
        "taxation",
    }
)

#: Modules that are neither: shared plumbing that carries no sector meaning.
SHARED_MODULES: frozenset[str] = frozenset({"errors"})


def layer_of(module: str) -> str | None:
    """The layer owning ``module``, or ``None`` when it is not classified."""
    if module in PLATFORM_MODULES:
        return "platform"
    if module in APPAREL_MODULES:
        return "apparel"
    if module in SHARED_MODULES:
        return "shared"
    return None
