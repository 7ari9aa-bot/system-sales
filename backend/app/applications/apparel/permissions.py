"""The permissions FIHRIST Apparel defines for its own functions.

Platform permissions (manage the account, the subscription, the members) live
in the platform layer. Everything a shop employee can do inside the store is
declared here, namespaced ``apparel.``, and owned by an apparel module. The
application is the only thing that decides which screen and which API needs
which code (industry-applications §13).
"""

from __future__ import annotations

from dataclasses import dataclass

NAMESPACE = "apparel."


@dataclass(frozen=True, slots=True)
class ApparelPermission:
    """One permission code, the module that owns it, and what it allows.

    Attributes:
        code: ``apparel.<area>.<action>``.
        module: An ``ApparelModule.key``.
        title_ar: What the owner reads in the roles screen.
        title_en: What the code and the audit trail say.
    """

    code: str
    module: str
    title_ar: str
    title_en: str


PERMISSIONS: tuple[ApparelPermission, ...] = (
    ApparelPermission("apparel.dashboard.view", "reporting", "عرض لوحة التحكم", "View dashboard"),
    ApparelPermission("apparel.products.view", "catalog", "عرض المنتجات", "View products"),
    ApparelPermission("apparel.products.create", "catalog", "إضافة منتج", "Create products"),
    ApparelPermission("apparel.products.edit", "catalog", "تعديل منتج", "Edit products"),
    ApparelPermission("apparel.products.delete", "catalog", "حذف منتج", "Delete products"),
    ApparelPermission("apparel.products.import", "catalog", "استيراد منتجات", "Import products"),
    ApparelPermission("apparel.inventory.view", "inventory", "عرض المخزون", "View inventory"),
    ApparelPermission("apparel.inventory.adjust", "inventory", "تسوية المخزون", "Adjust stock"),
    ApparelPermission("apparel.inventory.count", "inventory", "الجرد", "Count stock"),
    ApparelPermission("apparel.inventory.transfer", "inventory", "تحويل مخزون", "Transfer stock"),
    ApparelPermission("apparel.purchases.view", "purchasing", "عرض المشتريات", "View purchases"),
    ApparelPermission(
        "apparel.purchases.create", "purchasing", "إنشاء أمر شراء", "Create purchases"
    ),
    ApparelPermission(
        "apparel.purchases.receive", "purchasing", "استلام بضاعة", "Receive purchases"
    ),
    ApparelPermission(
        "apparel.purchases.approve", "purchasing", "اعتماد مشتريات", "Approve purchases"
    ),
    ApparelPermission("apparel.pos.access", "pos", "الدخول على الكاشير", "Access POS"),
    ApparelPermission("apparel.pos.sell", "pos", "إتمام بيع", "Sell at POS"),
    ApparelPermission("apparel.pos.discount", "pos", "منح خصم", "Give a discount"),
    ApparelPermission("apparel.pos.cancel_sale", "pos", "إلغاء عملية بيع", "Cancel a sale"),
    ApparelPermission("apparel.sales.view", "sales", "عرض المبيعات", "View sales"),
    ApparelPermission("apparel.sales.correct", "sales", "تصحيح عملية بيع", "Correct a sale"),
    ApparelPermission("apparel.returns.view", "returns", "عرض المرتجعات", "View returns"),
    ApparelPermission("apparel.returns.create", "returns", "تسجيل مرتجع", "Create a return"),
    ApparelPermission("apparel.returns.approve", "returns", "اعتماد مرتجع", "Approve a return"),
    ApparelPermission("apparel.customers.view", "customers", "عرض العملاء", "View customers"),
    ApparelPermission("apparel.customers.edit", "customers", "تعديل بيانات عميل", "Edit customers"),
    ApparelPermission("apparel.reports.view", "reporting", "عرض التقارير", "View reports"),
    ApparelPermission("apparel.reports.export", "reporting", "تصدير التقارير", "Export reports"),
    ApparelPermission(
        "apparel.integrations.view", "integrations", "عرض التكاملات", "View integrations"
    ),
    ApparelPermission(
        "apparel.integrations.manage", "integrations", "إدارة التكاملات", "Manage integrations"
    ),
    ApparelPermission("apparel.ai.manage", "ai", "إعدادات الذكاء الاصطناعي", "Manage AI settings"),
)

_BY_CODE: dict[str, ApparelPermission] = {permission.code: permission for permission in PERMISSIONS}


def permission_codes() -> tuple[str, ...]:
    return tuple(permission.code for permission in PERMISSIONS)


def get_permission(code: str) -> ApparelPermission:
    """The permission named ``code``; unknown codes fail closed."""
    try:
        return _BY_CODE[code]
    except KeyError:  # pragma: no cover - the message is the point
        raise KeyError(f"unknown apparel permission: {code!r}") from None


def codes_for_module(module: str) -> tuple[str, ...]:
    return tuple(p.code for p in PERMISSIONS if p.module == module)


#: The action verbs that change data. Read verbs (view, access) are everything else.
WRITE_ACTIONS: frozenset[str] = frozenset(
    {
        "adjust",
        "approve",
        "cancel_sale",
        "correct",
        "count",
        "create",
        "delete",
        "discount",
        "edit",
        "import",
        "manage",
        "receive",
        "sell",
        "transfer",
    }
)


#: Verbs that take data out without changing it. Kept apart from writes on
#: purpose: a workspace whose licence lapsed to read-only may still export its
#: own reports, and refusing that would be holding the owner's data hostage.
EGRESS_ACTIONS: frozenset[str] = frozenset({"export"})


def is_write_code(permission_code: str) -> bool:
    """Does this permission change data? The verb is the code's last segment."""
    return permission_code.rsplit(".", 1)[-1] in WRITE_ACTIONS


def is_egress_code(permission_code: str) -> bool:
    """Does this permission move data out of the store without changing it?"""
    return permission_code.rsplit(".", 1)[-1] in EGRESS_ACTIONS
