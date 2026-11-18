"""Settings Registry — the single source of truth for every setting key.

Every setting the system knows about is defined ONCE here. The registry
tells the resolver what type the value is, what scopes can override it,
what the factory default is, and how to validate a proposed value.

This is a STATIC registry: it lives in code, not in the database. Adding
a new setting is a code change (a new ``SettingDef``), never a row insert.
The database stores OVERRIDES against these definitions; the definitions
themselves are the contract.

Usage::

    from app.modules.settings.registry import REGISTRY, get_definition

    defn = get_definition("pos.max_discount_pct")
    defn.validate(15.0)  # raises ValueError if invalid
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class SettingType(enum.StrEnum):
    BOOL = "bool"
    NUMBER = "number"
    STRING = "string"
    ENUM = "enum"
    LIST = "list"


class Scope(enum.StrEnum):
    TENANT = "tenant"
    BRANCH = "branch"
    WAREHOUSE = "warehouse"
    POS_PROFILE = "pos_profile"
    REGISTER = "register"
    CHANNEL = "channel"
    USER = "user"


# The inheritance chain: each scope inherits from its parent.
# Branches inherit from tenant, warehouses from branch, etc.
SCOPE_PARENT: dict[Scope, Scope | None] = {
    Scope.TENANT: None,
    Scope.BRANCH: Scope.TENANT,
    Scope.WAREHOUSE: Scope.BRANCH,
    Scope.POS_PROFILE: Scope.WAREHOUSE,
    Scope.REGISTER: Scope.POS_PROFILE,
    Scope.CHANNEL: Scope.TENANT,
    Scope.USER: Scope.TENANT,
}


@dataclass(frozen=True, slots=True)
class SettingDef:
    """The contract for one configuration key.

    Attributes:
        key: Dotted identifier (e.g. "pos.require_customer").
        domain: Which part of the system owns this (pos, inventory, etc.).
        type: The JSON-safe type (bool, number, string, enum, list).
        default: Factory default when no override exists at any scope.
        scopes: Which scopes MAY override this setting. The first element
                is the LOWEST scope that makes sense; ``tenant`` is always
                implied as the highest.
        allowed_values: For ``enum`` type: the closed list of allowed values.
        min_value: For ``number`` type: inclusive minimum.
        max_value: For ``number`` type: inclusive maximum.
        max_length: For ``string`` type: maximum character length.
        permission: The permission code required to change this setting.
                    Default "settings:write".
        audit: Whether changes to this setting are recorded in the audit
               log (all changes are recorded in settings_history regardless).
        label_ar: Arabic display label for the UI.
        label_en: English display label for the UI.
        description_ar: Arabic description for the UI.
        description_en: English description for the UI.
    """

    key: str
    domain: str
    type: SettingType
    default: Any = None
    scopes: tuple[Scope, ...] = (Scope.TENANT,)
    allowed_values: tuple[str, ...] | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = None
    permission: str = "settings:write"
    audit: bool = False
    label_ar: str = ""
    label_en: str = ""
    description_ar: str = ""
    description_en: str = ""

    def validate(self, value: Any) -> Any:
        """Validate and coerce a proposed value. Raises ValueError on bad input."""
        if value is None and self.default is None:
            return None

        if self.type == SettingType.BOOL:
            if not isinstance(value, bool):
                raise ValueError(f"{self.key}: expected bool, got {type(value).__name__}")
            return value

        if self.type == SettingType.NUMBER:
            if isinstance(value, bool):
                raise ValueError(f"{self.key}: expected number, got bool")
            if not isinstance(value, (int, float, Decimal)):
                raise ValueError(f"{self.key}: expected number, got {type(value).__name__}")
            num = float(value)
            if self.min_value is not None and num < self.min_value:
                raise ValueError(f"{self.key}: value {num} below minimum {self.min_value}")
            if self.max_value is not None and num > self.max_value:
                raise ValueError(f"{self.key}: value {num} above maximum {self.max_value}")
            return num

        if self.type == SettingType.STRING:
            if not isinstance(value, str):
                raise ValueError(f"{self.key}: expected string, got {type(value).__name__}")
            if self.max_length is not None and len(value) > self.max_length:
                raise ValueError(
                    f"{self.key}: string length {len(value)} exceeds max {self.max_length}"
                )
            return value

        if self.type == SettingType.ENUM:
            if not isinstance(value, str):
                raise ValueError(f"{self.key}: expected string, got {type(value).__name__}")
            if self.allowed_values and value not in self.allowed_values:
                raise ValueError(f"{self.key}: value {value!r} not in {self.allowed_values}")
            return value

        if self.type == SettingType.LIST:
            if not isinstance(value, list):
                raise ValueError(f"{self.key}: expected list, got {type(value).__name__}")
            return value

        raise ValueError(f"{self.key}: unknown type {self.type}")  # pragma: no cover

    def scope_allowed(self, scope: Scope | str) -> bool:
        """Check whether a scope is allowed to override this setting."""
        s = Scope(scope) if isinstance(scope, str) else scope
        return s in self.scopes


# ---------------------------------------------------------------------------
# The registry: every setting the system knows about.
# ---------------------------------------------------------------------------

_DEFINITIONS: list[SettingDef] = []


def _reg(d: SettingDef) -> SettingDef:
    _DEFINITIONS.append(d)
    return d


# ======================= BUSINESS & SHOP PROFILE ==========================

_reg(
    SettingDef(
        key="business.legal_name",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=255,
        label_ar="الاسم القانوني",
        label_en="Legal Name",
    )
)
_reg(
    SettingDef(
        key="business.trade_name",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=255,
        label_ar="الاسم التجاري",
        label_en="Trade Name",
    )
)
_reg(
    SettingDef(
        key="business.tax_id",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=63,
        audit=True,
        label_ar="الرقم الضريبي",
        label_en="Tax ID",
    )
)
_reg(
    SettingDef(
        key="business.commercial_register",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=63,
        label_ar="السجل التجاري",
        label_en="Commercial Register",
    )
)
_reg(
    SettingDef(
        key="business.phone",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=31,
        label_ar="رقم الهاتف",
        label_en="Phone",
    )
)
_reg(
    SettingDef(
        key="business.email",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=320,
        label_ar="البريد الإلكتروني",
        label_en="Email",
    )
)
_reg(
    SettingDef(
        key="business.website",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=255,
        label_ar="الموقع الإلكتروني",
        label_en="Website",
    )
)
_reg(
    SettingDef(
        key="business.address.line1",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=255,
        label_ar="العنوان",
        label_en="Address Line 1",
    )
)
_reg(
    SettingDef(
        key="business.address.city",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=127,
        label_ar="المدينة",
        label_en="City",
    )
)
_reg(
    SettingDef(
        key="business.address.postal_code",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=15,
        label_ar="الرمز البريدي",
        label_en="Postal Code",
    )
)
_reg(
    SettingDef(
        key="business.type",
        domain="business",
        type=SettingType.ENUM,
        default="retail",
        scopes=(Scope.TENANT,),
        allowed_values=("retail", "fnb", "services", "wholesale"),
        label_ar="نوع النشاط",
        label_en="Business Type",
    )
)

# ============================= POS & SALES ================================

_reg(
    SettingDef(
        key="pos.require_customer",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        label_ar="العميل إلزامي",
        label_en="Require Customer",
        description_ar="هل يجب تحديد عميل قبل إتمام البيع؟",
        description_en="Must a customer be selected before completing a sale?",
    )
)
_reg(
    SettingDef(
        key="pos.default_payment_method",
        domain="pos",
        type=SettingType.ENUM,
        default="cash",
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        allowed_values=("cash", "card", "wallet", "bank_transfer"),
        label_ar="وسيلة التحصيل الافتراضية",
        label_en="Default Payment Method",
    )
)
_reg(
    SettingDef(
        key="pos.max_discount_pct",
        domain="pos",
        type=SettingType.NUMBER,
        default=None,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        min_value=0,
        max_value=100,
        audit=True,
        label_ar="الحد الأقصى للخصم %",
        label_en="Max Discount %",
        description_ar="أقصى خصم يمكن للكاشير تطبيقه (% من الإجمالي).",
        description_en="Maximum discount a cashier can apply (% of total).",
    )
)
_reg(
    SettingDef(
        key="pos.allow_hold_cart",
        domain="pos",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.POS_PROFILE),
        label_ar="تعليق الفاتورة",
        label_en="Allow Hold Cart",
    )
)
_reg(
    SettingDef(
        key="pos.require_session",
        domain="pos",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.BRANCH),
        label_ar="إلزام بدء الوردية",
        label_en="Require Session",
        description_ar="لا يمكن البيع قبل فتح وردية كاشير.",
        description_en="Sales require an open POS session.",
    )
)
_reg(
    SettingDef(
        key="pos.opening_float_required",
        domain="pos",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.BRANCH),
        label_ar="رصيد بداية الوردية",
        label_en="Opening Float Required",
    )
)
_reg(
    SettingDef(
        key="pos.allow_negative_stock_sale",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        label_ar="السماح بالبيع من مخزون سالب",
        label_en="Allow Negative Stock Sale",
    )
)
_reg(
    SettingDef(
        key="pos.deduct_stock_on",
        domain="pos",
        type=SettingType.ENUM,
        default="sale",
        scopes=(Scope.TENANT,),
        allowed_values=("sale", "confirm", "ship"),
        label_ar="وقت خصم المخزون",
        label_en="Deduct Stock On",
        description_ar="متى تُخصم الكمية من المخزون.",
        description_en="When inventory is deducted for a sale.",
    )
)
_reg(
    SettingDef(
        key="pos.return_requires_receipt",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH),
        label_ar="إلزام إيصال المرتجع",
        label_en="Return Requires Receipt",
    )
)
_reg(
    SettingDef(
        key="pos.return_max_days",
        domain="pos",
        type=SettingType.NUMBER,
        default=30,
        scopes=(Scope.TENANT, Scope.BRANCH),
        min_value=0,
        max_value=365,
        label_ar="مهلة المرتجع (أيام)",
        label_en="Return Window (Days)",
    )
)
_reg(
    SettingDef(
        key="pos.allowed_payment_methods",
        domain="pos",
        type=SettingType.LIST,
        default=["cash", "card", "wallet", "bank_transfer"],
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        label_ar="وسائل التحصيل المسموحة",
        label_en="Allowed Payment Methods",
    )
)

# ============================== INVENTORY =================================

_reg(
    SettingDef(
        key="inventory.allow_negative",
        domain="inventory",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        label_ar="السماح بمخزون سالب",
        label_en="Allow Negative Stock",
    )
)
_reg(
    SettingDef(
        key="inventory.auto_reserve",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="حجز تلقائي للطلبات",
        label_en="Auto Reserve for Orders",
    )
)
_reg(
    SettingDef(
        key="inventory.reserve_ttl_minutes",
        domain="inventory",
        type=SettingType.NUMBER,
        default=1440,
        scopes=(Scope.TENANT,),
        min_value=5,
        max_value=43200,
        label_ar="مدة الحجز (دقائق)",
        label_en="Reservation TTL (Minutes)",
    )
)
_reg(
    SettingDef(
        key="inventory.fifo_enabled",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="تفعيل FIFO",
        label_en="Enable FIFO Costing",
    )
)
_reg(
    SettingDef(
        key="inventory.track_locations",
        domain="inventory",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        label_ar="تفعيل مواقع التخزين",
        label_en="Track Warehouse Locations",
    )
)
_reg(
    SettingDef(
        key="inventory.quality_check_on_receipt",
        domain="inventory",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        label_ar="الفحص عند الاستلام",
        label_en="Quality Check on Receipt",
        description_ar="هل البضاعة تحتاج فحص قبل دخول المخزون القابل للبيع؟",
        description_en="Goods require inspection before entering sellable stock.",
    )
)
_reg(
    SettingDef(
        key="inventory.stocktake_approval_required",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        label_ar="اعتماد الجرد",
        label_en="Stocktake Requires Approval",
    )
)
_reg(
    SettingDef(
        key="inventory.safety_stock_default",
        domain="inventory",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        min_value=0,
        max_value=1000000,
        label_ar="مخزون الأمان الافتراضي",
        label_en="Default Safety Stock",
    )
)

# ============================== PURCHASING ================================

_reg(
    SettingDef(
        key="purchasing.approval_required",
        domain="purchasing",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH),
        audit=True,
        label_ar="اعتماد أمر الشراء",
        label_en="PO Requires Approval",
    )
)
_reg(
    SettingDef(
        key="purchasing.approval_threshold",
        domain="purchasing",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT, Scope.BRANCH),
        min_value=0,
        label_ar="حد مبلغ الاعتماد",
        label_en="Approval Threshold Amount",
    )
)
_reg(
    SettingDef(
        key="purchasing.allow_partial_receipt",
        domain="purchasing",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="السماح بالاستلام الجزئي",
        label_en="Allow Partial Receipt",
    )
)
_reg(
    SettingDef(
        key="purchasing.allow_over_receipt",
        domain="purchasing",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="السماح باستلام أكثر من المطلوب",
        label_en="Allow Over Receipt",
    )
)
_reg(
    SettingDef(
        key="purchasing.centralized",
        domain="purchasing",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="شراء مركزي",
        label_en="Centralized Purchasing",
        description_ar="أوامر الشراء تصدر مركزيًا لا من كل فرع.",
        description_en="Purchase orders are issued centrally, not per branch.",
    )
)

# =============================== ORDERS ===================================

_reg(
    SettingDef(
        key="orders.reserve_on",
        domain="orders",
        type=SettingType.ENUM,
        default="create",
        scopes=(Scope.TENANT,),
        allowed_values=("create", "confirm"),
        label_ar="وقت حجز المخزون",
        label_en="Reserve Stock On",
    )
)
_reg(
    SettingDef(
        key="orders.allow_backorder",
        domain="orders",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.CHANNEL),
        label_ar="السماح بالطلب المسبق",
        label_en="Allow Backorder",
    )
)
_reg(
    SettingDef(
        key="orders.deduct_stock_on",
        domain="orders",
        type=SettingType.ENUM,
        default="confirm",
        scopes=(Scope.TENANT,),
        allowed_values=("confirm", "ship", "deliver"),
        label_ar="وقت خصم مخزون الطلبات",
        label_en="Deduct Stock On (Orders)",
    )
)

# ======================== PRINT & DOCUMENTS ===============================

_reg(
    SettingDef(
        key="print.paper_width",
        domain="print",
        type=SettingType.ENUM,
        default="80mm",
        scopes=(Scope.TENANT, Scope.REGISTER),
        allowed_values=("58mm", "80mm", "a4"),
        label_ar="عرض الورق",
        label_en="Paper Width",
    )
)
_reg(
    SettingDef(
        key="print.show_logo",
        domain="print",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.REGISTER),
        label_ar="إظهار الشعار",
        label_en="Show Logo",
    )
)
_reg(
    SettingDef(
        key="print.header_text",
        domain="print",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=500,
        label_ar="نص أعلى الإيصال",
        label_en="Receipt Header Text",
    )
)
_reg(
    SettingDef(
        key="print.footer_text",
        domain="print",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=500,
        label_ar="نص أسفل الإيصال",
        label_en="Receipt Footer Text",
    )
)
_reg(
    SettingDef(
        key="print.copies",
        domain="print",
        type=SettingType.NUMBER,
        default=1,
        scopes=(Scope.TENANT, Scope.REGISTER),
        min_value=1,
        max_value=5,
        label_ar="عدد نسخ الطباعة",
        label_en="Print Copies",
    )
)
_reg(
    SettingDef(
        key="print.show_tax_detail",
        domain="print",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="تفصيل الضريبة على الإيصال",
        label_en="Show Tax Detail",
    )
)
_reg(
    SettingDef(
        key="print.barcode_format",
        domain="print",
        type=SettingType.ENUM,
        default="code128",
        scopes=(Scope.TENANT,),
        allowed_values=("code128", "ean13", "upc_a", "qr"),
        label_ar="صيغة الباركود",
        label_en="Barcode Format",
    )
)
_reg(
    SettingDef(
        key="print.invoice_prefix",
        domain="print",
        type=SettingType.STRING,
        default="INV",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=15,
        label_ar="بادئة رقم الفاتورة",
        label_en="Invoice Number Prefix",
    )
)

# ======================== NOTIFICATIONS ===================================

_reg(
    SettingDef(
        key="notifications.low_stock_alert",
        domain="notifications",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        label_ar="تنبيه نقص المخزون",
        label_en="Low Stock Alert",
    )
)
_reg(
    SettingDef(
        key="notifications.order_received",
        domain="notifications",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.USER),
        label_ar="تنبيه طلب جديد",
        label_en="New Order Notification",
    )
)

# ---------------------------------------------------------------------------
# Build the lookup dict (frozen after module load).
# ---------------------------------------------------------------------------

REGISTRY: dict[str, SettingDef] = {d.key: d for d in _DEFINITIONS}


def get_definition(key: str) -> SettingDef:
    """Look up a setting definition by key. Raises KeyError if unknown."""
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"Unknown setting key: {key!r}") from None


def list_definitions(*, domain: str | None = None) -> list[SettingDef]:
    """Return all definitions, optionally filtered by domain."""
    if domain is None:
        return list(_DEFINITIONS)
    return [d for d in _DEFINITIONS if d.domain == domain]


def domains() -> list[str]:
    """Return the unique domain names, in registration order."""
    seen: set[str] = set()
    result: list[str] = []
    for d in _DEFINITIONS:
        if d.domain not in seen:
            seen.add(d.domain)
            result.append(d.domain)
    return result
