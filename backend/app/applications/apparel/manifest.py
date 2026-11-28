"""What FIHRIST Apparel is made of, fixed for this release.

The database may decide whether a workspace bought the application and whether
its licence is active. It may never decide what the application can do: a row
cannot invent a module or a route. So the definition lives in code, here, and
the tables carry commerce and installation state only.

Each module names the real backend packages that implement it. That is the part
that makes this file worth reading: a module with no package behind it would be
a slide, not software, and ``test_apparel_application`` refuses it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApparelModule:
    """One functional area of the apparel application.

    Attributes:
        key: Stable identifier, used in permissions, routes and events.
        title_ar: Arabic name shown to the owner.
        title_en: English name, used in code and logs.
        backend_modules: Packages under ``app/applications/apparel/modules`` that
            implement it.
        settings_domains: Settings registry domains this module owns.
        events: Domain events it publishes (industry-applications §17).
    """

    key: str
    title_ar: str
    title_en: str
    backend_modules: tuple[str, ...]
    settings_domains: tuple[str, ...] = ()
    events: tuple[str, ...] = ()


MODULES: tuple[ApparelModule, ...] = (
    ApparelModule(
        key="catalog",
        title_ar="المنتجات والتصنيفات",
        title_en="Catalog & Products",
        backend_modules=("catalog",),
        settings_domains=("catalog", "capability"),
        events=("ProductCreated", "VariantUpdated"),
    ),
    ApparelModule(
        key="inventory",
        title_ar="المخزون",
        title_en="Inventory",
        backend_modules=("inventory",),
        settings_domains=("inventory",),
        events=("InventoryAdjusted", "StockCounted", "StockTransferred"),
    ),
    ApparelModule(
        key="purchasing",
        title_ar="المشتريات والموردون",
        title_en="Purchasing & Suppliers",
        backend_modules=("purchasing",),
        settings_domains=("purchasing",),
        events=("PurchaseReceived", "SupplierReturned"),
    ),
    ApparelModule(
        key="pos",
        title_ar="الكاشير",
        title_en="POS",
        backend_modules=("pos",),
        settings_domains=("pos", "print"),
        events=("ShiftClosed", "CashMoved"),
    ),
    ApparelModule(
        key="sales",
        title_ar="المبيعات",
        title_en="Sales",
        backend_modules=("orders",),
        settings_domains=("orders", "pricing", "einvoice"),
        events=("SaleCompleted", "SaleCorrected"),
    ),
    # Returns are not a package of their own: a POS return writes pos_return_lines
    # and a refund writes orders.refunds. Naming both packages is the honest map.
    ApparelModule(
        key="returns",
        title_ar="المرتجعات والاستبدال",
        title_en="Returns & Exchanges",
        backend_modules=("pos", "orders"),
        events=("ReturnCompleted", "ExchangeCompleted"),
    ),
    ApparelModule(
        key="customers",
        title_ar="العملاء",
        title_en="Customers",
        backend_modules=("customers", "customer_accounts", "segments"),
        events=("CustomerCreated", "CustomerMerged"),
    ),
    ApparelModule(
        key="reporting",
        title_ar="التقارير والتحليلات",
        title_en="Reporting & Analytics",
        backend_modules=("analytics", "financial"),
        events=(),
    ),
    ApparelModule(
        key="integrations",
        title_ar="التكاملات والقنوات",
        title_en="Integrations",
        backend_modules=("conversations", "marketing"),
        settings_domains=("notifications",),
        events=("ChannelConnected", "CampaignSent"),
    ),
    ApparelModule(
        key="ai",
        title_ar="الذكاء الاصطناعي",
        title_en="AI",
        backend_modules=("ai",),
        settings_domains=("customer_agent", "analytics_agent"),
        events=("AgentEscalated",),
    ),
)


@dataclass(frozen=True, slots=True)
class ApparelManifest:
    """The application's identity and its registries."""

    key: str
    industry: str
    version: str
    title_ar: str
    title_en: str
    modules: tuple[ApparelModule, ...]
    entrypoint: str
    routes_registry: str
    permissions_registry: str
    settings_registry: str


APP_MANIFEST = ApparelManifest(
    key="apparel",
    industry="apparel",
    version="1.0.0",
    title_ar="FIHRIST للملابس",
    title_en="FIHRIST Apparel",
    modules=MODULES,
    entrypoint="/apparel/dashboard",
    routes_registry="app.applications.apparel.routes",
    permissions_registry="app.applications.apparel.permissions",
    settings_registry="app.applications.apparel.settings_ownership",
)


def module_keys() -> tuple[str, ...]:
    return tuple(module.key for module in MODULES)


def get_module(key: str) -> ApparelModule:
    """The module named ``key``; an unknown key is a programming error.

    Failing closed matters here for the same reason it matters in the
    application registry: a typo must never read as "no restriction".
    """
    for module in MODULES:
        if module.key == key:
            return module
    raise KeyError(f"unknown apparel module: {key!r}")
