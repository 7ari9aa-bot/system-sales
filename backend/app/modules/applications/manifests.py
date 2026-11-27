"""The manifest registry — what each application is, in code.

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


REGISTRY: dict[str, ApplicationManifest] = {
    m.key: m
    for m in (
        ApplicationManifest(
            key="retail.core",
            version=1,
            title_ar="النظام الأساسي للمتاجر",
            title_en="Retail Core",
            category="core",
            owner_domain="catalog",
            api_groups=("products", "categories", "inventory", "pos", "orders", "expenses"),
            settings_sections=("products", "inventory", "pos", "receipts"),
            navigation_group="core",
            setup_flow="retail_core_setup",
            notes_ar=(
                "المنتجات والمقاسات والألوان والباركود والمخزون الأساسي "
                "والكاشير والمرتجعات والورديات."
            ),
        ),
        ApplicationManifest(
            key="retail.purchasing",
            version=1,
            title_ar="المشتريات والموردون",
            title_en="Purchasing & Suppliers",
            category="operations",
            owner_domain="purchasing",
            dependencies=("retail.core",),
            api_groups=("suppliers", "purchase-orders", "goods-receipts", "supplier-returns"),
            settings_sections=("purchasing",),
            setup_flow="purchasing_setup",
            notes_ar="الموردون وأوامر الشراء واستلام البضاعة وفحص الجودة ومرتجعات الموردين.",
        ),
        ApplicationManifest(
            key="retail.warehouse",
            version=1,
            title_ar="إدارة المستودعات",
            title_en="Warehouse Management",
            category="operations",
            owner_domain="inventory",
            dependencies=("retail.core",),
            api_groups=("warehouses", "transfers", "locations-bins"),
            settings_sections=("warehouses",),
            setup_flow="warehouse_setup",
            notes_ar="مخازن متعددة ومواقع ورفوف وتحويلات بين المخازن والفروع.",
        ),
        ApplicationManifest(
            key="retail.inventory_advanced",
            version=1,
            title_ar="المخزون المتقدم",
            title_en="Advanced Inventory",
            category="operations",
            owner_domain="inventory",
            dependencies=("retail.core", "retail.warehouse"),
            api_groups=("replenishment", "valuation", "landed-cost", "traceability"),
            settings_sections=("inventory-advanced",),
            setup_flow="advanced_inventory_setup",
            requires_capabilities=("lot_expiry",),
            notes_ar="التجديد وإعادة الشراء والتقييم وLanded Cost والدفعات والسيريال عند الحاجة.",
        ),
        ApplicationManifest(
            key="customer.engagement",
            version=1,
            title_ar="العملاء والرسائل",
            title_en="Customer Engagement",
            category="growth",
            owner_domain="conversations",
            dependencies=("retail.core",),
            api_groups=("customers", "inbox", "channels", "integrations"),
            settings_sections=("channels", "customers"),
            setup_flow="channels_setup",
            notes_ar="إدارة العملاء وصندوق الرسائل الموحد وقنوات التواصل والتكاملات.",
        ),
        ApplicationManifest(
            key="ai.customer_support",
            version=1,
            title_ar="مساعد خدمة العملاء",
            title_en="Customer Agent",
            category="intelligence",
            owner_domain="ai",
            dependencies=("retail.core", "customer.engagement"),
            api_groups=("ai-chat", "voice"),
            settings_sections=("customer-agent",),
            setup_flow="agent_setup",
            notes_ar="مساعد نصي وصوتي للعملاء يجاوب من بيانات المتجر ويصعّد لموظف بشري.",
        ),
        ApplicationManifest(
            key="ai.business_intelligence",
            version=1,
            title_ar="التحليلات الذكية",
            title_en="Business Intelligence",
            category="intelligence",
            owner_domain="analytics",
            dependencies=("retail.core",),
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
    manifest = REGISTRY.get(key)
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
