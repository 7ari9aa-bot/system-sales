"""The manifest registry — what each application is, in code.

There is no shared Business Core here. The base application IS the sector
application (``apparel``); the other entries are that application's own
extensions, and every one of them is namespaced under it. A second sector gets
its own application with its own modules, never a seat on a common core
(industry-applications §1, §21 "no shared Retail Core").

``LEGACY_KEYS`` carries the keys a deployed database may still hold from before
the rename. They resolve to their new owner so a migration that has not run yet
cannot close a paid screen.


The database may decide whether an application is *for sale*, *at what price*,
and *whether this workspace bought it*. It may never decide what the application
can do: a row cannot invent a route or run code. So capabilities live here, in
the release, and the tables carry commerce and installation state only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ApplicationManifest:
    """One application, fixed for this release of the platform."""

    key: str
    version: int
    title_ar: str
    title_en: str
    category: str
    #: The module that owns the business rules behind this application.
    owner_domain: str
    #: Applications that must be active first. An empty tuple means standalone.
    dependencies: tuple[str, ...] = ()
    #: Industries this product is sold to. ``*`` means every industry.
    supported_industries: tuple[str, ...] = ("*",)
    #: API route groups this application authorizes (used by require_application).
    api_groups: tuple[str, ...] = ()
    #: Settings sections that only make sense once this is installed.
    settings_sections: tuple[str, ...] = ()
    navigation_group: str = "operations"
    #: The setup flow a workspace must finish before the app is usable.
    setup_flow: str | None = None
    #: Capabilities the app needs switched on to work at all.
    requires_capabilities: tuple[str, ...] = ()
    notes_ar: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


#: Old key -> current key. Read-only compatibility: nothing new may be written
#: under an old key, and every entry here is removed once the data migration has
#: run everywhere.
#:
#: Production ran `migrations/sql/rename_retail_core_to_apparel.sql` on
#: 2026-11-28: zero legacy keys remain in plan_application_inclusions,
#: subscription_items and workspace_app_installations, and 1610 inclusions now
#: read `apparel*`. The bridge stays until every environment has migrated (a dev
#: database restored from an older backup would still carry the old keys), and
#: `tests/test_rename_retail_core_migration.py` proves the rename and its
#: rollback on a real Postgres before it is ever pointed at production again.
LEGACY_KEYS: dict[str, str] = {
    "retail.core": "apparel",
    "retail.purchasing": "apparel.purchasing",
    "retail.warehouse": "apparel.warehouse",
    "retail.inventory_advanced": "apparel.inventory_advanced",
    "customer.engagement": "apparel.customers",
    "ai.customer_support": "apparel.ai_support",
    "ai.business_intelligence": "apparel.ai_intelligence",
}


def normalize_key(key: str) -> str:
    """The current key for ``key``, following one legacy hop."""
    return LEGACY_KEYS.get(key, key)


REGISTRY: dict[str, ApplicationManifest] = {
    m.key: m
    for m in (
        ApplicationManifest(
            # The sector application itself. It owns the shop's whole trading
            # surface; nothing here is a base another sector would sit on.
            key="apparel",
            version=1,
            title_ar="FIHRIST للملابس",
            title_en="FIHRIST Apparel",
            category="industry",
            owner_domain="catalog",
            api_groups=(
                "products",
                "categories",
                "inventory",
                "pos",
                "orders",
                "expenses",
                "customers",
                "reports",
            ),
            settings_sections=("business", "products", "inventory", "pos", "receipts"),
            navigation_group="industry",
            setup_flow="apparel_setup",
            notes_ar=(
                "المنتجات والمقاسات والألوان والباركود والمخزون والكاشير "
                "والمرتجعات والورديات."
            ),
        ),
        ApplicationManifest(
            key="apparel.purchasing",
            version=1,
            title_ar="المشتريات والموردون",
            title_en="Purchasing & Suppliers",
            category="operations",
            owner_domain="purchasing",
            dependencies=("apparel",),
            api_groups=("suppliers", "purchase-orders", "goods-receipts", "supplier-returns"),
            settings_sections=("purchasing",),
            setup_flow="purchasing_setup",
            notes_ar="الموردون وأوامر الشراء واستلام البضاعة وفحص الجودة ومرتجعات الموردين.",
        ),
        ApplicationManifest(
            key="apparel.warehouse",
            version=1,
            title_ar="إدارة المستودعات",
            title_en="Warehouse Management",
            category="operations",
            owner_domain="inventory",
            dependencies=("apparel",),
            api_groups=("warehouses", "transfers", "locations-bins"),
            settings_sections=("warehouses",),
            setup_flow="warehouse_setup",
            notes_ar="مخازن متعددة ومواقع ورفوف وتحويلات بين المخازن والفروع.",
        ),
        ApplicationManifest(
            key="apparel.inventory_advanced",
            version=1,
            title_ar="المخزون المتقدم",
            title_en="Advanced Inventory",
            category="operations",
            owner_domain="inventory",
            dependencies=("apparel", "apparel.warehouse"),
            api_groups=("replenishment", "valuation", "landed-cost", "traceability"),
            settings_sections=("inventory-advanced",),
            setup_flow="advanced_inventory_setup",
            requires_capabilities=("lot_expiry",),
            notes_ar="التجديد وإعادة الشراء والتقييم وLanded Cost والدفعات والسيريال عند الحاجة.",
        ),
        ApplicationManifest(
            key="apparel.customers",
            version=1,
            title_ar="العملاء والرسائل",
            title_en="Customer Engagement",
            category="growth",
            owner_domain="conversations",
            dependencies=("apparel",),
            api_groups=("customers", "inbox", "channels", "integrations"),
            settings_sections=("channels", "customers"),
            setup_flow="channels_setup",
            notes_ar="إدارة العملاء وصندوق الرسائل الموحد وقنوات التواصل والتكاملات.",
        ),
        ApplicationManifest(
            key="apparel.ai_support",
            version=1,
            title_ar="مساعد خدمة العملاء",
            title_en="Customer Agent",
            category="intelligence",
            owner_domain="ai",
            dependencies=("apparel", "apparel.customers"),
            api_groups=("ai-chat", "voice"),
            settings_sections=("customer-agent",),
            setup_flow="agent_setup",
            notes_ar="مساعد نصي وصوتي للعملاء يجاوب من بيانات المتجر ويصعّد لموظف بشري.",
        ),
        ApplicationManifest(
            key="apparel.ai_intelligence",
            version=1,
            title_ar="التحليلات الذكية",
            title_en="Business Intelligence",
            category="intelligence",
            owner_domain="analytics",
            dependencies=("apparel",),
            api_groups=("analytics", "sales-intelligence"),
            settings_sections=("analytics",),
            setup_flow="analytics_setup",
            notes_ar="تحليلات المبيعات والمخزون والمؤشرات المتقدمة واستخراج النتائج والتوصيات.",
        ),
    )
}


def all_manifests() -> tuple[ApplicationManifest, ...]:
    return tuple(REGISTRY[key] for key in sorted(REGISTRY))


def get_manifest(key: str) -> ApplicationManifest:
    """The manifest for ``key``; an unknown key is a programming error.

    Applications fail closed: an unknown key must never be treated as "no
    restriction", which is how a typo would silently open a paid product.
    """
    manifest = REGISTRY.get(normalize_key(key))
    if manifest is None:
        raise KeyError(f"unknown application: {key!r}")
    return manifest


def resolve_installation_order(keys: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Dependencies first, each key once — the order an install must follow."""
    ordered: list[str] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(key: str) -> None:
        if key in done:
            return
        if key in visiting:
            raise ValueError(f"application dependency cycle at {key!r}")
        manifest = get_manifest(key)
        visiting.add(key)
        for dependency in manifest.dependencies:
            visit(dependency)
        visiting.discard(key)
        done.add(key)
        ordered.append(key)

    for key in keys:
        visit(key)
    return tuple(ordered)


def applications_for_industry(industry: str) -> tuple[ApplicationManifest, ...]:
    """Applications sold to ``industry``, dependencies included."""
    return tuple(
        m
        for m in all_manifests()
        if "*" in m.supported_industries or industry in m.supported_industries
    )


def validate_registry() -> list[str]:
    """Problems with the registry itself; empty means the release is coherent.

    Runs as a test, not at import: a broken registry must fail the build, never
    the first request that happens to touch a paid application.
    """
    problems: list[str] = []
    for key, manifest in REGISTRY.items():
        if manifest.key != key:
            problems.append(f"{key}: key does not match its registry entry")
        if not manifest.api_groups:
            problems.append(f"{key}: declares no api_groups, so nothing is gated by it")
        if not manifest.owner_domain:
            problems.append(f"{key}: declares no owner_domain")
        if not manifest.supported_industries:
            problems.append(f"{key}: declares no supported_industries")
        for dependency in manifest.dependencies:
            if dependency not in REGISTRY:
                problems.append(f"{key}: depends on unknown application {dependency!r}")
            elif dependency == key:
                problems.append(f"{key}: depends on itself")
    try:
        resolve_installation_order(tuple(REGISTRY))
    except ValueError as cycle:
        problems.append(str(cycle))
    except KeyError as unknown:
        problems.append(f"dependency resolution hit {unknown}")
    return problems
