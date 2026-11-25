"""Business-type presets — a one-click starting configuration with composition.

Each preset is a dict of ``{setting_key: value}`` applied at the
tenant scope. They are starting points; the merchant changes whatever
they want after. The names match the onboarding wizard choices:

* ``physical_retail``: a shop that sells face-to-face with a POS till.
* ``ecommerce``: an online store receiving orders from channels.
* ``omnichannel``: POS + online in the same inventory.
* ``enterprise``: multiple branches, centralised purchasing, approvals.

Composition (§170): a preset may ``extends`` another. The parent's values are
merged first; the child's values override. Resolution is recursive and
cycle-free (a cycle raises at import time). The flat ``PRESETS`` dict that
callers have always used holds the fully-merged result, so existing code is
unchanged; ``PRESET_DEFS`` holds the structured definitions with the
``extends`` link and labels.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PresetDef:
    """Structured metadata for one preset, separate from its merged values.

    ``values`` are the keys this preset sets itself — NOT the inherited ones.
    ``extends`` names the parent whose values are merged underneath. The
    flat ``PRESETS`` dict holds the merged result; this dataclass holds the
    intent.
    """

    name: str
    values: dict[str, object]
    extends: str | None = None
    label_ar: str = ""
    label_en: str = ""
    description_ar: str = ""
    description_en: str = ""


# ------------------------------------------------------------------ raw defs
# NOTE (needs a product decision): ecommerce, omnichannel and enterprise set
# ``inventory.reserve_ttl_minutes`` to 1440 (24 h). That is now a real behaviour, not a label:
# applying the preset makes an unpaid order hold stock for a day, where the order flow has always
# held it for 15 minutes. It suits cash-on-delivery, and starves stock for card checkout. The
# registry default is 15 so a shop that applies no preset is unchanged.

_PRESET_DEFS: dict[str, PresetDef] = {
    # ---- Preset 1: محل أرضي ------------------------------------------
    "physical_retail": PresetDef(
        name="physical_retail",
        label_ar="محل أرضي",
        label_en="Physical Retail",
        description_ar="محل يبيع وجهاً لوجه عبر كاشير",
        description_en="A shop that sells face-to-face with a POS till",
        values={
            "business.type": "retail",
            "pos.require_customer": False,
            "pos.allow_hold_cart": True,
            "pos.return_max_days": 30,
            "inventory.auto_reserve": False,
            "inventory.fifo_enabled": False,
            "inventory.track_locations": False,
            "inventory.quality_check_on_receipt": False,
            "purchasing.approval_required": False,
            "purchasing.allow_partial_receipt": True,
            "print.paper_width": "80mm",
            "print.copies": 1,
            "notifications.low_stock_alert": True,
        },
    ),
    # ---- Preset 2: متجر إلكتروني (extends physical_retail) -------------
    "ecommerce": PresetDef(
        name="ecommerce",
        extends="physical_retail",
        label_ar="متجر إلكتروني",
        label_en="E-Commerce",
        description_ar="متجر إلكتروني يستقبل الطلبات من القنوات",
        description_en="An online store receiving orders from channels",
        values={
            "pos.require_customer": True,
            "inventory.auto_reserve": True,
            "inventory.reserve_ttl_minutes": 1440,
            "inventory.fifo_enabled": True,
            "orders.reserve_on": "create",
            "orders.allow_backorder": False,
            "orders.deduct_stock_on": "confirm",
            "notifications.order_received": True,
        },
    ),
    # ---- Preset 3: متجر هجين (extends physical_retail) ----------------
    "omnichannel": PresetDef(
        name="omnichannel",
        extends="physical_retail",
        label_ar="متجر هجين",
        label_en="Omnichannel",
        description_ar="كاشير + متجر إلكتروني بنفس المخزون",
        description_en="POS + online in the same inventory",
        values={
            "inventory.auto_reserve": True,
            "inventory.reserve_ttl_minutes": 1440,
            "inventory.fifo_enabled": True,
            "orders.reserve_on": "create",
            "orders.allow_backorder": False,
            "notifications.order_received": True,
        },
    ),
    # ---- Preset 4: سلسلة فروع (extends omnichannel) -------------------
    "enterprise": PresetDef(
        name="enterprise",
        extends="omnichannel",
        label_ar="سلسلة فروع",
        label_en="Enterprise",
        description_ar="فروع متعددة، شراء مركزي، موافقات",
        description_en="Multiple branches, centralised purchasing, approvals",
        values={
            "pos.max_discount_pct": 10.0,
            "pos.return_max_days": 14,
            "inventory.track_locations": True,
            "inventory.quality_check_on_receipt": True,
            "inventory.stocktake_approval_required": True,
            "purchasing.approval_required": True,
            "purchasing.approval_threshold": 5000,
            "purchasing.centralized": True,
        },
    ),
    # ---- Preset 5: محل ملابس أرضي (extends physical_retail) -------------
    # Chosen on purpose by the owner (POST /settings/presets/apparel_ground_shop); picking the
    # apparel vertical alone never applies it, so a shop that already chose apparel keeps working
    # as it does. Everything here is a value for a switch that already exists. The last three hide
    # the screens a one-store, walk-in-only shop does not use (transfers between warehouses, online
    # stock allocation, units of measure); they hide only, and the owner can turn any back on.
    "apparel_ground_shop": PresetDef(
        name="apparel_ground_shop",
        extends="physical_retail",
        label_ar="محل ملابس أرضي",
        label_en="Apparel Ground Shop",
        description_ar="فرع واحد، كاشير واحد، نقدي",
        description_en="Single-store, single-till, cash-only apparel shop",
        values={
            "business.vertical": "apparel",
            # money: the till takes cash, sells to a walk-in, never on account
            "pos.take_payments": True,
            "pos.allow_sale_on_account": False,
            "pos.variance_reason_required": True,
            # a ground shop that takes card must count the terminal too, or the card total is the
            # one figure nobody ever checks against the bank
            "pos.settle_payment_methods": True,
            "pos.return_restock_default": True,
            # stock: one place, no batches or serials, no online holds, no shelf locations
            "inventory.fifo_enabled": True,
            "inventory.stocktake_approval_required": True,
            "inventory.show_warehouse_transfers": False,
            "inventory.show_channel_allocation": False,
            "inventory.show_units_of_measure": False,
            "capability.serial_tracking": False,
            "capability.lot_expiry": False,
            "capability.fefo_picking": False,
            "capability.weight_scale": False,
            "capability.variant_matrix": True,
            # buying: no approval chain, one shop so nothing is centralised
            "purchasing.centralized": False,
            "notifications.order_received": False,
        },
    ),
}


# ------------------------------------------------------------------ resolution


def _resolve_preset_values(name: str, _seen: set[str] | None = None) -> dict[str, object]:
    """Recursively merge a preset with its parent. Cycle-safe.

    The parent's values are merged first; the child's values override.
    ``_seen`` tracks the chain to detect cycles (a programming error).
    """
    if name not in _PRESET_DEFS:
        raise KeyError(f"unknown preset {name!r}")
    seen = _seen or set()
    if name in seen:
        chain = " -> ".join(list(seen) + [name])
        raise ValueError(f"preset extends cycle detected: {chain}")
    seen = seen | {name}

    defn = _PRESET_DEFS[name]
    if defn.extends is None:
        return dict(defn.values)
    parent = _resolve_preset_values(defn.extends, seen)
    return {**parent, **defn.values}


# The flat dict callers have always used — fully merged, no ``extends`` keys.
PRESETS: dict[str, dict[str, object]] = {
    name: _resolve_preset_values(name) for name in _PRESET_DEFS
}

#: Structured definitions with the ``extends`` link and labels.
PRESET_DEFS: dict[str, PresetDef] = _PRESET_DEFS


def resolve_preset(name: str) -> dict[str, object]:
    """Return the fully-merged values for a named preset (public API)."""
    return _resolve_preset_values(name)


def preset_chain(name: str) -> list[str]:
    """Return the inheritance chain from root to this preset (e.g. for display)."""
    chain: list[str] = []
    current: str | None = name
    seen: set[str] = set()
    while current is not None:
        if current in seen:
            raise ValueError(f"preset extends cycle at {current!r}")
        seen.add(current)
        chain.append(current)
        current = _PRESET_DEFS[current].extends
    chain.reverse()
    return chain
