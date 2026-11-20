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


# The business segments (``business.type``) a setting can belong to. The platform serves many kinds
# of shop and each sees only the settings that mean something to it: a restaurant has no use for
# FIFO costing of shelf stock, a services business no use for a till's return window. ``()`` on a
# definition means "every segment", so a key is shared until someone narrows it on purpose.
SEGMENTS: tuple[str, ...] = ("retail", "fnb", "services", "wholesale")

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
        permission: The permission code required to change this setting at TENANT level.
                    Default "settings:write".
        branch_delegable: True when a ``settings:branch_write`` holder may set it at a
                scope below tenant. Enforced by ``policy.authorize_write``.
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
    # May a holder of settings:branch_write (a manager) set this key below tenant level?
    # Money rules, tax identity and anything that changes how stock is valued stay owner-only.
    branch_delegable: bool = False
    audit: bool = False
    # Which business segments this setting applies to; () = all of them. Only narrows what the
    # settings screen shows: a hidden key still resolves to its default, so code that reads it
    # never has to know the segment.
    segments: tuple[str, ...] = ()
    label_ar: str = ""
    label_en: str = ""
    description_ar: str = ""
    description_en: str = ""

    @property
    def enforced(self) -> bool:
        """Does any code outside the settings module act on this key yet?

        The registry was written ahead of the code that reads it. A key that is stored and shown
        but never read is a switch wired to nothing: the owner flips it and the shop behaves
        the same. The UI uses this to mark such keys "not active yet" instead of implying they
        work. ``ENFORCED_KEYS`` is kept honest by tests/test_settings_enforced_keys.py.
        """
        return self.key in ENFORCED_KEYS

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


# Keys some module outside app/modules/settings actually reads, and where. Add a key here in the
# same commit that wires it; the guard test fails if a listed key is not read, or a read key is
# not listed.
ENFORCED_KEYS: frozenset[str] = frozenset(
    {
        "pos.max_discount_pct",  # pos/service.py::_discount_ceiling
        "inventory.reserve_ttl_minutes",  # orders/service.py::reservation_ttl
        "pos.allow_hold_cart",  # pos/service.py::hold_cart
        "pos.return_max_days",  # pos/service.py::return_sale
        "pos.exchange_max_days",  # pos/service.py::exchange
        "pos.return_restock_default",  # pos/service.py::return_sale, exchange
        "pos.return_reasons",  # pos/service.py::_clean_return_reason
        "purchasing.allow_over_receipt",  # purchasing/service.py::GoodsReceiptService.create
        "pos.require_customer",  # pos/service.py::_resolve_customer
        "pos.take_payments",  # pos/service.py::record_sale
        "pos.reference_required_methods",  # pos/service.py::record_sale
        "purchasing.allow_partial_receipt",  # purchasing/service.py::GoodsReceiptService.create
        "inventory.safety_stock_default",  # inventory/services/replenishment.py::set_policy
    }
)


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
        description_ar="الاسم المسجّل رسمياً للمنشأة كما يظهر في الفواتير والمستندات الرسمية.",
        description_en="The officially registered name, shown on invoices and legal documents.",
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
        description_ar="الاسم الذي يعرفه به العملاء إن اختلف عن الاسم القانوني.",
        description_en="The name customers know you by, when it differs from the legal name.",
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
        description_ar="رقم التسجيل الضريبي للمنشأة.",
        description_en="The business's tax registration number.",
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
        description_ar="رقم السجل التجاري للمنشأة.",
        description_en="The business's commercial register number.",
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
        branch_delegable=True,
        label_ar="رقم الهاتف",
        label_en="Phone",
        description_ar="رقم هاتف المنشأة للتواصل.",
        description_en="The business's contact phone number.",
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
        branch_delegable=True,
        label_ar="البريد الإلكتروني",
        label_en="Email",
        description_ar="البريد الإلكتروني الرسمي للمنشأة.",
        description_en="The business's official email address.",
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
        description_ar="عنوان موقع المنشأة على الإنترنت.",
        description_en="The business's website address.",
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
        branch_delegable=True,
        label_ar="العنوان",
        label_en="Address Line 1",
        description_ar="عنوان المنشأة: الشارع والمبنى.",
        description_en="The business's street address.",
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
        branch_delegable=True,
        label_ar="المدينة",
        label_en="City",
        description_ar="المدينة التي تقع فيها المنشأة.",
        description_en="The city where the business is located.",
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
        branch_delegable=True,
        label_ar="الرمز البريدي",
        label_en="Postal Code",
        description_ar="الرمز البريدي لعنوان المنشأة.",
        description_en="The postal code of the business's address.",
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
        description_ar="نوع النشاط، ويحدد الإعدادات التي تظهر لك: تجزئة، مطاعم، خدمات، أو جملة.",
        description_en="The kind of business. It decides which settings you see.",
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
        branch_delegable=True,
        label_ar="العميل إلزامي",
        label_en="Require Customer",
        description_ar="هل يجب تحديد عميل قبل إتمام البيع؟",
        description_en="Must a customer be selected before completing a sale?",
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
        branch_delegable=True,
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
        branch_delegable=True,
        label_ar="تعليق الفاتورة",
        label_en="Allow Hold Cart",
        description_ar="السماح بتعليق فاتورة وإكمالها لاحقاً.",
        description_en="Lets the cashier park a cart and finish it later.",
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
        branch_delegable=True,
        label_ar="مهلة المرتجع (أيام)",
        label_en="Return Window (Days)",
        description_ar="أقصى عدد أيام بعد البيع يُقبل فيها المرتجع.",
        description_en="The most days after a sale that a return is still accepted.",
    )
)
_reg(
    SettingDef(
        key="pos.exchange_max_days",
        domain="pos",
        type=SettingType.NUMBER,
        # 0 = "same as the return window": a shop that never touches this behaves exactly as one
        # that sets it equal to pos.return_max_days. Before this setting an exchange had NO time
        # limit at all, so a shop that wants the old behaviour can set it to 365.
        default=0,
        scopes=(Scope.TENANT, Scope.BRANCH),
        min_value=0,
        max_value=365,
        branch_delegable=True,
        label_ar="مهلة الاستبدال (أيام)",
        label_en="Exchange Window (Days)",
        description_ar="أقصى عدد أيام بعد البيع يُقبل فيها الاستبدال. صفر يعني نفس مهلة المرتجع.",
        description_en="Most days after a sale an exchange is accepted. 0 = same as returns.",
    )
)
_reg(
    SettingDef(
        key="pos.return_restock_default",
        domain="pos",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.BRANCH),
        branch_delegable=True,
        label_ar="إرجاع القطعة للرف افتراضياً",
        label_en="Restock Returned Items by Default",
        description_ar="القيمة الابتدائية لخيار إرجاع القطعة المرتجعة للمخزون. يغيّرها الكاشير.",
        description_en="The starting choice for putting a returned item back on the shelf.",
    )
)
_reg(
    SettingDef(
        key="pos.return_reasons",
        domain="pos",
        type=SettingType.LIST,
        default=["size", "defect", "changed_mind", "wrong_item"],
        scopes=(Scope.TENANT,),
        label_ar="أسباب المرتجع",
        label_en="Return Reasons",
        description_ar="الأسباب التي يختار منها الكاشير عند المرتجع. تُسجَّل مع كل قطعة.",
        description_en="The reasons a cashier can pick from on a return. Saved on each item.",
    )
)
_reg(
    SettingDef(
        key="pos.take_payments",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="تسجيل وسائل الدفع",
        label_en="Record Payments at the Till",
        description_ar=(
            "عند التفعيل يسجّل الكاشير كيف دفع الزبون (كاش أو كارت أو تحويل) والباقي، "
            "وتدخل المبالغ النقدية في حركة الدرج. عند الإيقاف يسجّل البيع فقط كما كان."
        ),
        description_en=(
            "When on, the cashier records how the customer paid (cash, card, transfer) and the "
            "change, and cash goes into the drawer ledger. When off, a sale is recorded only."
        ),
    )
)
_reg(
    SettingDef(
        key="pos.reference_required_methods",
        domain="pos",
        type=SettingType.LIST,
        default=["card", "bank_transfer", "wallet"],
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="وسائل دفع تتطلب رقماً مرجعياً",
        label_en="Payment Methods That Need a Reference",
        description_ar=(
            "وسائل الدفع التي يجب أن يكتب الكاشير معها رقم العملية أو الموافقة "
            "(مثل رقم إيصال ماكينة الكارت أو رقم تحويل إنستاباي)."
        ),
        description_en=(
            "Payment methods that need an approval or transfer number typed by the cashier "
            "(a card terminal slip number, an instant-transfer reference)."
        ),
    )
)
# ============================== INVENTORY =================================
#
# There is deliberately no "allow negative stock" switch here (nor pos.allow_negative_stock_sale).
# The inventory ledger invariant is that on-hand never goes below zero; a per-shop toggle would
# let one tenant break it. Add one only together with the ledger change that makes it safe.

_reg(
    SettingDef(
        key="inventory.auto_reserve",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="حجز تلقائي للطلبات",
        label_en="Auto Reserve for Orders",
        description_ar="حجز مخزون الطلب تلقائياً عند إنشائه.",
        description_en="Reserve an order's stock automatically when it is created.",
    )
)
_reg(
    SettingDef(
        key="inventory.reserve_ttl_minutes",
        domain="inventory",
        type=SettingType.NUMBER,
        # 15 is what the order flow has always used (orders.service._RESERVATION_TTL). The default
        # must equal the behaviour a shop already has: a shop that never touches this setting must
        # not wake up holding abandoned carts for a day.
        default=15,
        scopes=(Scope.TENANT,),
        min_value=5,
        max_value=43200,
        label_ar="مدة الحجز (دقائق)",
        label_en="Reservation TTL (Minutes)",
        description_ar="المدة بالدقائق التي يُحجز فيها مخزون طلب غير مدفوع قبل أن يُفرج عنه.",
        description_en="How many minutes an unpaid order holds its stock before it is released.",
    )
)
_reg(
    SettingDef(
        key="inventory.fifo_enabled",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        segments=("retail", "fnb", "wholesale"),
        label_ar="تفعيل FIFO",
        label_en="Enable FIFO Costing",
        description_ar="تقييم تكلفة البضاعة المباعة بالأقدم دخولاً أولاً (FIFO).",
        description_en="Value cost of goods sold oldest-first (FIFO).",
    )
)
_reg(
    SettingDef(
        key="inventory.track_locations",
        domain="inventory",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        branch_delegable=True,
        segments=("retail", "fnb", "wholesale"),
        label_ar="تفعيل مواقع التخزين",
        label_en="Track Warehouse Locations",
        description_ar="تتبّع مكان كل صنف داخل المستودع (رف، ممر، صندوق).",
        description_en="Track where each item sits inside a warehouse (shelf, aisle, bin).",
    )
)
_reg(
    SettingDef(
        key="inventory.quality_check_on_receipt",
        domain="inventory",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.WAREHOUSE),
        branch_delegable=True,
        segments=("retail", "fnb", "wholesale"),
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
        branch_delegable=True,
        segments=("retail", "fnb", "wholesale"),
        label_ar="اعتماد الجرد",
        label_en="Stocktake Requires Approval",
        description_ar="لا يُطبَّق الجرد على الأرصدة إلا بعد اعتماد مسؤول.",
        description_en="A stocktake changes balances only after a manager approves it.",
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
        branch_delegable=True,
        segments=("retail", "fnb", "wholesale"),
        label_ar="مخزون الأمان الافتراضي",
        label_en="Default Safety Stock",
        description_ar="مخزون الأمان المعتمد لصنف لم يُحدَّد له مخزون أمان خاص.",
        description_en="The safety buffer used for an item that states none of its own.",
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
        description_ar="إلزام اعتماد أمر الشراء قبل إرساله للمورد.",
        description_en="Require a purchase order to be approved before it goes to the supplier.",
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
        description_ar="المبلغ الذي يلزم اعتماد أمر الشراء إذا تجاوزه.",
        description_en="The amount above which a purchase order needs approval.",
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
        description_ar="السماح باستلام جزء من كمية أمر الشراء، وإلا يلزم استلام المتبقي كاملاً.",
        description_en="Allow receiving part of an order; if off, receive the full remainder.",
    )
)
_reg(
    SettingDef(
        key="purchasing.allow_over_receipt",
        domain="purchasing",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        segments=("retail", "fnb", "wholesale"),
        label_ar="السماح باستلام أكثر من المطلوب",
        label_en="Allow Over Receipt",
        description_ar="السماح باستلام كمية أكبر من المطلوبة في أمر الشراء.",
        description_en="Allow receiving more than the purchase order asked for.",
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
        description_ar="اللحظة التي يُحجز فيها مخزون الطلب: عند إنشائه أو عند تأكيده.",
        description_en="When an order's stock is reserved: on creation or on confirmation.",
    )
)
_reg(
    SettingDef(
        key="orders.allow_backorder",
        domain="orders",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.CHANNEL),
        branch_delegable=True,
        segments=("retail", "fnb", "wholesale"),
        label_ar="السماح بالطلب المسبق",
        label_en="Allow Backorder",
        description_ar="قبول طلب صنف رصيده غير كافٍ على أن يُوفَّر لاحقاً.",
        description_en="Accept an order for an item without enough stock, to be fulfilled later.",
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
        description_ar="اللحظة التي يُخصم فيها مخزون الطلب: التأكيد أو الشحن أو التسليم.",
        description_en="When an order's stock is deducted: on confirmation, shipping or delivery.",
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
        branch_delegable=True,
        label_ar="عرض الورق",
        label_en="Paper Width",
        description_ar="عرض ورق الطباعة: 58 أو 80 مم أو A4.",
        description_en="Receipt paper width: 58mm, 80mm or A4.",
    )
)
_reg(
    SettingDef(
        key="print.show_logo",
        domain="print",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.REGISTER),
        branch_delegable=True,
        label_ar="إظهار الشعار",
        label_en="Show Logo",
        description_ar="إظهار شعار المنشأة أعلى الإيصال.",
        description_en="Show the business logo at the top of the receipt.",
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
        branch_delegable=True,
        label_ar="نص أعلى الإيصال",
        label_en="Receipt Header Text",
        description_ar="نص حر يُطبع أعلى الإيصال.",
        description_en="Free text printed at the top of the receipt.",
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
        branch_delegable=True,
        label_ar="نص أسفل الإيصال",
        label_en="Receipt Footer Text",
        description_ar="نص حر يُطبع أسفل الإيصال، مثل شكر العميل أو سياسة الاستبدال.",
        description_en="Free text printed at the bottom of the receipt (thanks, return policy).",
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
        branch_delegable=True,
        label_ar="عدد نسخ الطباعة",
        label_en="Print Copies",
        description_ar="عدد النسخ المطبوعة من كل إيصال.",
        description_en="How many copies of each receipt are printed.",
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
        description_ar="إظهار تفصيل الضريبة في الإيصال.",
        description_en="Show the tax breakdown on the receipt.",
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
        description_ar="صيغة الباركود المطبوع على الإيصال والملصقات.",
        description_en="The barcode format printed on receipts and labels.",
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
        branch_delegable=True,
        label_ar="بادئة رقم الفاتورة",
        label_en="Invoice Number Prefix",
        description_ar="حروف تسبق رقم الفاتورة، مثل INV.",
        description_en="Letters placed before the invoice number, such as INV.",
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
        branch_delegable=True,
        label_ar="تنبيه نقص المخزون",
        label_en="Low Stock Alert",
        description_ar="تنبيهك عندما ينخفض رصيد صنف عن حده الأدنى.",
        description_en="Alert you when an item's stock falls below its minimum.",
    )
)
_reg(
    SettingDef(
        key="notifications.order_received",
        domain="notifications",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.USER),
        branch_delegable=True,
        label_ar="تنبيه طلب جديد",
        label_en="New Order Notification",
        description_ar="تنبيهك عند وصول طلب جديد.",
        description_en="Alert you when a new order arrives.",
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


def list_definitions(*, domain: str | None = None, segment: str | None = None) -> list[SettingDef]:
    """Return all definitions, optionally for one domain and/or one business segment.

    A segment keeps the keys that name it AND every key that names none (those apply to everyone).
    """
    result = list(_DEFINITIONS)
    if domain is not None:
        result = [d for d in result if d.domain == domain]
    if segment is not None:
        result = [d for d in result if not d.segments or segment in d.segments]
    return result


def domains() -> list[str]:
    """Return the unique domain names, in registration order."""
    seen: set[str] = set()
    result: list[str] = []
    for d in _DEFINITIONS:
        if d.domain not in seen:
            seen.add(d.domain)
            result.append(d.domain)
    return result
