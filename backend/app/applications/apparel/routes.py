"""The screens FIHRIST Apparel serves, and where they live today.

Each route belongs to an apparel module and is declared under the
application's own prefix. ``legacy_path`` is the path the running frontend uses
today: the target architecture moves the shop under ``/apparel`` without
breaking a bookmark or an emailed link, so both exist until the redirect is
retired (industry-applications §11).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Routes that belong to the application shell, not to a trading module.
SHELL = "__shell__"

PREFIX = "/apparel"


@dataclass(frozen=True, slots=True)
class ApparelRoute:
    """One screen: where it lives, what owns it, and what it used to be."""

    path: str
    module: str
    title_ar: str
    legacy_path: str | None = None


ROUTES: tuple[ApparelRoute, ...] = (
    ApparelRoute("/apparel/dashboard", SHELL, "لوحة التحكم", "/dashboard"),
    ApparelRoute("/apparel/pos", "pos", "الكاشير", "/pos"),
    ApparelRoute("/apparel/products", "catalog", "المنتجات", "/products"),
    ApparelRoute("/apparel/products/new", "catalog", "منتج جديد", "/products/new"),
    ApparelRoute("/apparel/inventory", "inventory", "المخزون", "/inventory"),
    ApparelRoute("/apparel/purchases", "purchasing", "المشتريات", "/supply-chain"),
    ApparelRoute("/apparel/suppliers", "purchasing", "الموردون"),
    ApparelRoute("/apparel/sales", "sales", "المبيعات", "/orders"),
    ApparelRoute("/apparel/returns", "returns", "المرتجعات"),
    ApparelRoute("/apparel/customers", "customers", "العملاء", "/customers"),
    ApparelRoute("/apparel/inbox", "integrations", "صندوق الرسائل", "/inbox"),
    ApparelRoute("/apparel/marketing", "integrations", "الحملات", "/marketing/*"),
    ApparelRoute("/apparel/assistant", "ai", "المساعد الذكي", "/assistant"),
    ApparelRoute("/apparel/reports", "reporting", "التقارير"),
    ApparelRoute("/apparel/settings", SHELL, "إعدادات المتجر"),
)


def route_paths() -> tuple[str, ...]:
    return tuple(route.path for route in ROUTES)


def routes_for_module(module: str) -> tuple[ApparelRoute, ...]:
    return tuple(route for route in ROUTES if route.module == module)


def legacy_paths() -> tuple[str, ...]:
    return tuple(route.legacy_path for route in ROUTES if route.legacy_path)
