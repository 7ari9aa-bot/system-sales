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
    "pos": "apparel",
    "activity": "apparel",
    "reports": "apparel",
    "shop-type": "apparel",
    "activity-setup": "apparel",
    # Reading the registry is how the interface learns what exists, so it cannot
    # itself be gated by a product; it answers "which products" for all of them.
    "applications": "apparel",
    "inventory": "apparel",
    "catalog": "apparel",
    "products": "apparel",
    "variants": "apparel",
    "categories": "apparel",
    "brands": "apparel",
    "identifiers": "apparel",
    "apparel": "apparel",
    "imports": "apparel",
    "options": "apparel",
    "website-platform": "apparel",
    "expenses": "apparel",
    "orders": "apparel",
    "shipments": "apparel",
    # --- retail.warehouse ---
    "warehouses": "apparel.warehouse",
    # --- retail.purchasing ---
    "suppliers": "apparel.purchasing",
    "purchase-orders": "apparel.purchasing",
    "goods-receipts": "apparel.purchasing",
    "supplier-returns": "apparel.purchasing",
    "supplier-payments": "apparel.purchasing",
    "variant-costs": "apparel.purchasing",
    # --- customer.engagement ---
    "customers": "apparel.customers",
    "invitations": "apparel.customers",
    "integrations": "apparel.customers",
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
