"""THE route map. Edit only this file to say what a route belongs to.

Every route group in scope has one line in ``GROUPS``: the module that owns it and the capability
it needs (``core`` means every shop has it, whatever its vertical). A route that needs a capability
the rest of its group does not is named in ``CAPABILITY_ROUTES`` (first match wins).

Adding a route inside a group that is already listed needs no edit. A route in a NEW group, or a new
capability, fails ``tests/test_route_map.py`` until it is listed here, which is the point.
Capability names come from ``settings/capabilities.py`` ``CAPABILITIES``; the test rejects any
other name. Groups outside ``SCOPE_MODULES`` are reported as unmapped and tolerated until they are
onboarded by adding their module to ``SCOPE_MODULES`` and their groups below.

``scope``: core = every shop, vertical = only shops whose capability is on.

HOW TO ADD A NEW VERTICAL (for example a pharmacy that really behaves differently)
A vertical is data. It never needs an ``if vertical == ...`` in code. Touch these, in order:

1. ``modules/settings/capabilities.py``: put the vertical in ``VERTICALS`` and add its name to
   ``on_for`` of each capability it starts with. A new behaviour is a new ``Capability`` row.
2. ``core/shop_type.py``: add it to ``CHOOSABLE_VERTICALS`` ONLY once it changes behaviour. The
   owner is never offered a choice that does nothing (``tests/test_vertical_choice.py`` pins this).
3. ``modules/settings/presets.py``: add a preset only if the vertical needs starting settings.
4. This file: a new route group gets one line in ``GROUPS``. A route that needs the new
   capability goes in ``CAPABILITY_ROUTES``. Nothing else here changes.
5. Run ``tests/test_route_map.py``, ``test_capabilities.py`` and ``test_vertical_choice.py``.

Adding a route to a group that is already listed needs no edit here.
"""

from __future__ import annotations

from dataclasses import dataclass

CORE = "core"

# Modules this map is responsible for in the first pass. Everything else is "unmapped".
SCOPE_MODULES: frozenset[str] = frozenset(
    {
        "pos",
        "inventory",
        "purchasing",
        "catalog",
        "expenses",
        "orders",
        "customers",
        "activity",
        "core.profit_report",
        "core.sell_through_report",
        "core.dead_stock_report",
        "core.season_markdown",
        "core.shop_type",
        "core.activity_setup",
    }
)


@dataclass(frozen=True)
class Group:
    """``module`` owns the group; ``also`` lists other modules serving routes under it."""

    module: str
    capability: str = CORE
    note: str = ""
    also: tuple[str, ...] = ()

    def owns(self, module: str) -> bool:
        return module == self.module or module in self.also


# key = first path segment after /api/v1
GROUPS: dict[str, Group] = {
    # --- cashier ---
    "pos": Group("pos", note="registers, shifts, cash movements, selling, returns, exchanges"),
    "activity": Group("activity", note="the audit trail the cashier reads"),
    "reports": Group(
        "core.profit_report",
        note="profit and sell-through by model / colour / size",
        also=("core.sell_through_report", "core.dead_stock_report"),
    ),
    "shop-type": Group(
        "core.shop_type", note="the owner picks the vertical (apparel, pharmacy, ...)"
    ),
    "activity-setup": Group(
        "core.activity_setup", note="first-run setup: pick the vertical once, or skip"
    ),
    # --- inventory ---
    "inventory": Group("inventory", note="balances, movements, transfers, stocktakes, reports"),
    # --- catalog ---
    "catalog": Group("core.season_markdown", note="take a percent off a whole season"),
    "products": Group("catalog"),
    "variants": Group("catalog"),
    "categories": Group("catalog"),
    "brands": Group("catalog"),
    "warehouses": Group("catalog"),
    "identifiers": Group("catalog"),
    "apparel": Group("catalog", note="shop-owned size sets and colours"),
    "imports": Group("catalog", note="CSV import"),
    "website-platform": Group(
        "catalog",
        also=("orders",),
        note="storefront catalog read (catalog) and order intake (orders), API-key access",
    ),
    "options": Group("catalog", note="product option graph"),
    # --- purchasing ---
    "suppliers": Group("purchasing"),
    "purchase-orders": Group("purchasing"),
    "goods-receipts": Group("purchasing"),
    "supplier-returns": Group("purchasing"),
    "supplier-payments": Group("purchasing"),
    "variant-costs": Group("purchasing"),
    # --- expenses / orders / customers ---
    "expenses": Group("expenses"),
    "orders": Group("orders"),
    "shipments": Group("orders"),
    "customers": Group("customers"),
    "invitations": Group("customers"),
    "integrations": Group("customers", note="Meta / WhatsApp connection of the shop"),
}

# Routes that need a capability: (path fragment, capability), first match wins. Nothing in the code
# gates on these yet, so this records the intent and the test keeps the names honest.
CAPABILITY_ROUTES: tuple[tuple[str, str], ...] = (
    ("/matrix", "variant_matrix"),
    ("/apparel/", "variant_matrix"),
    ("/apparel-insights", "variant_matrix"),
    ("/lots", "lot_expiry"),
    ("/expiry-report", "lot_expiry"),
    ("/serials", "serial_tracking"),
    ("/tracking-policy", "serial_tracking"),
)


def capability_of(path: str, group: Group) -> str:
    """The capability a route needs: a named exception first, else its group's, else ``core``."""
    for fragment, capability in CAPABILITY_ROUTES:
        if fragment in path:
            return capability
    return group.capability


def scope_of(capability: str) -> str:
    return "core" if capability == CORE else "vertical"
