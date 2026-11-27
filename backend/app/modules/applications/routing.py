"""Which application a route group belongs to.

``route_map`` answers "which module owns this path". This answers the next
question, the one a customer pays for: "which product is this path part of".
Keeping them separate is what lets one shop buy purchasing without buying a
warehouse, while ``catalog`` and ``inventory`` modules keep serving both.

Nothing gates on this yet — the tables that record installations do not exist.
The mapping is here, and tested for coverage, so that when enforcement lands
there is no route whose owner was never decided.
"""

from __future__ import annotations

#: key = first path segment after /api/v1 (the same keys route_map uses)
GROUP_APPLICATIONS: dict[str, str] = {
    # --- retail.core: the base every shop starts with ---
    "pos": "retail.core",
    "activity": "retail.core",
    "reports": "retail.core",
    "shop-type": "retail.core",
    "activity-setup": "retail.core",
    "inventory": "retail.core",
    "catalog": "retail.core",
    "products": "retail.core",
    "variants": "retail.core",
    "categories": "retail.core",
    "brands": "retail.core",
    "identifiers": "retail.core",
    "apparel": "retail.core",
    "imports": "retail.core",
    "options": "retail.core",
    "website-platform": "retail.core",
    "expenses": "retail.core",
    "orders": "retail.core",
    "shipments": "retail.core",
    # --- retail.warehouse ---
    "warehouses": "retail.warehouse",
    # --- retail.purchasing ---
    "suppliers": "retail.purchasing",
    "purchase-orders": "retail.purchasing",
    "goods-receipts": "retail.purchasing",
    "supplier-returns": "retail.purchasing",
    "supplier-payments": "retail.purchasing",
    "variant-costs": "retail.purchasing",
    # --- customer.engagement ---
    "customers": "customer.engagement",
    "invitations": "customer.engagement",
    "integrations": "customer.engagement",
}


def application_for_group(group_key: str) -> str:
    """The application key owning ``group_key``; unknown is a programming error."""
    application = GROUP_APPLICATIONS.get(group_key)
    if application is None:
        raise KeyError(
            f"route group {group_key!r} belongs to no application — decide which "
            "product sells it before the group is reachable"
        )
    return application
