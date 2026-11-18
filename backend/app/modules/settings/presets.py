"""Business-type presets — a one-click starting configuration.

Each preset is a dict of ``{setting_key: value}`` applied at the
tenant scope. They are starting points; the merchant changes whatever
they want after. The names match the onboarding wizard choices:

* ``physical_retail``: a shop that sells face-to-face with a POS till.
* ``ecommerce``: an online store receiving orders from channels.
* ``omnichannel``: POS + online in the same inventory.
* ``enterprise``: multiple branches, centralised purchasing, approvals.
"""

from __future__ import annotations

# NOTE (needs a product decision): ecommerce, omnichannel and enterprise set
# ``inventory.reserve_ttl_minutes`` to 1440 (24 h). That is now a real behaviour, not a label:
# applying the preset makes an unpaid order hold stock for a day, where the order flow has always
# held it for 15 minutes. It suits cash-on-delivery, and starves stock for card checkout. The
# registry default is 15 so a shop that applies no preset is unchanged.
PRESETS: dict[str, dict[str, object]] = {
    # ---- Preset 1: محل أرضي ------------------------------------------
    "physical_retail": {
        "business.type": "retail",
        "pos.require_customer": False,
        "pos.default_payment_method": "cash",
        "pos.require_session": True,
        "pos.opening_float_required": True,
        "pos.allow_hold_cart": True,
        "pos.deduct_stock_on": "sale",
        "pos.return_requires_receipt": False,
        "pos.return_max_days": 30,
        "pos.allowed_payment_methods": ["cash", "card"],
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
    # ---- Preset 2: متجر إلكتروني --------------------------------------
    "ecommerce": {
        "business.type": "retail",
        "pos.require_customer": True,
        "pos.require_session": False,
        "pos.deduct_stock_on": "confirm",
        "inventory.auto_reserve": True,
        "inventory.reserve_ttl_minutes": 1440,
        "inventory.fifo_enabled": True,
        "orders.reserve_on": "create",
        "orders.allow_backorder": False,
        "orders.deduct_stock_on": "confirm",
        "purchasing.approval_required": False,
        "purchasing.allow_partial_receipt": True,
        "notifications.low_stock_alert": True,
        "notifications.order_received": True,
    },
    # ---- Preset 3: متجر هجين ------------------------------------------
    "omnichannel": {
        "business.type": "retail",
        "pos.require_customer": False,
        "pos.default_payment_method": "cash",
        "pos.require_session": True,
        "pos.opening_float_required": True,
        "pos.deduct_stock_on": "sale",
        "inventory.auto_reserve": True,
        "inventory.reserve_ttl_minutes": 1440,
        "inventory.fifo_enabled": True,
        "inventory.track_locations": False,
        "orders.reserve_on": "create",
        "orders.allow_backorder": False,
        "purchasing.approval_required": False,
        "purchasing.allow_partial_receipt": True,
        "print.paper_width": "80mm",
        "notifications.low_stock_alert": True,
        "notifications.order_received": True,
    },
    # ---- Preset 4: سلسلة فروع -----------------------------------------
    "enterprise": {
        "business.type": "retail",
        "pos.require_customer": False,
        "pos.default_payment_method": "cash",
        "pos.require_session": True,
        "pos.opening_float_required": True,
        "pos.max_discount_pct": 10.0,
        "pos.deduct_stock_on": "sale",
        "pos.return_requires_receipt": True,
        "pos.return_max_days": 14,
        "inventory.auto_reserve": True,
        "inventory.reserve_ttl_minutes": 1440,
        "inventory.fifo_enabled": True,
        "inventory.track_locations": True,
        "inventory.quality_check_on_receipt": True,
        "inventory.stocktake_approval_required": True,
        "purchasing.approval_required": True,
        "purchasing.approval_threshold": 5000,
        "purchasing.allow_partial_receipt": True,
        "purchasing.centralized": True,
        "orders.reserve_on": "create",
        "print.paper_width": "80mm",
        "notifications.low_stock_alert": True,
        "notifications.order_received": True,
    },
}
