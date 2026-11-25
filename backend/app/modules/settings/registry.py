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

from app.modules.settings.capabilities import CAPABILITIES, DEFAULT_VERTICAL, VERTICALS


class SettingType(enum.StrEnum):
    BOOL = "bool"
    NUMBER = "number"
    STRING = "string"
    ENUM = "enum"
    LIST = "list"


class ApplyMode(enum.StrEnum):
    """How a setting change reaches the runtime (§27 Change Management).

    * ``IMMEDIATE``: apply right after validation (UI prefs, display).
    * ``VALIDATED``: domain validation required before the change is accepted
      (inventory policies, POS rules, return windows).
    * ``APPROVAL_REQUIRED``: a second person must approve before the change
      is applied (sensitive cross-branch policies, high-risk financial caps).
    """

    IMMEDIATE = "immediate"
    VALIDATED = "validated"
    APPROVAL_REQUIRED = "approval_required"


class Sensitivity(enum.StrEnum):
    """Data sensitivity classification for a setting (§11, §76).

    * ``NORMAL``: visible and editable through the standard settings UI.
    * ``SENSITIVE``: access is restricted; value is masked in some views.
    * ``SECRET``: stored in the secrets store, never in the settings table;
      the UI shows only a connection status, never the value itself.
    """

    NORMAL = "normal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class Scope(enum.StrEnum):
    TENANT = "tenant"
    WORKSPACE = "workspace"
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
    # One business activity of the account (a clothes shop, a distribution company). A branch sits
    # inside a workspace, so a value set here reaches every branch under it.
    Scope.WORKSPACE: Scope.TENANT,
    Scope.BRANCH: Scope.WORKSPACE,
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
    # How the change reaches the runtime (§27). Defaults to VALIDATED: most
    # operational settings need domain checks before they are accepted. UI
    # preferences override to IMMEDIATE; security-critical keys use APPROVAL_REQUIRED.
    apply_mode: ApplyMode = ApplyMode.VALIDATED
    # Data sensitivity (§11, §76). NORMAL for ordinary settings; SENSITIVE for
    # restricted-access keys; SECRET for credentials stored in the secrets store.
    sensitivity: Sensitivity = Sensitivity.NORMAL
    # Entitlement/feature this setting belongs to (§72). When set, the
    # entitlements service is consulted before the value is accepted.
    feature_requirement: str | None = None
    # Whether this setting supports rollback to a previous revision (§35).
    # Most settings do; a few (channel credentials, SKU generation) do not.
    rollback_supported: bool = True
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
        "imports.legacy_csv_endpoint",  # catalog/routers/imports.py::import_products_csv
        # The shop's legal identity now reaches the receipt read model, so the four fields the
        # owner types there are read instead of stored and forgotten (pos/receipt_settings.py).
        "business.email",  # pos/receipt_settings.py::receipt_settings
        "business.website",  # pos/receipt_settings.py::receipt_settings
        "business.commercial_register",  # pos/receipt_settings.py::receipt_settings
        "business.address.postal_code",  # pos/receipt_settings.py::receipt_settings
        "pos.max_discount_pct",  # pos/service.py::_discount_ceiling
        "pos.cash_movement_limit",  # pos/service.py::add_cash_movement
        "inventory.reserve_ttl_minutes",  # orders/service.py::reservation_ttl
        "pos.allow_hold_cart",  # pos/service.py::hold_cart
        "pos.return_max_days",  # pos/service.py::return_sale
        "pos.exchange_max_days",  # pos/service.py::exchange
        "pos.return_restock_default",  # pos/service.py::return_sale, exchange
        "pos.refund_cash_only",  # pos/service.py::_settle_refund
        "pos.return_reasons",  # pos/service.py::_clean_return_reason
        "purchasing.allow_over_receipt",  # purchasing/service.py::GoodsReceiptService.create
        "pos.require_customer",  # pos/service.py::_resolve_customer
        "einvoice.eta_enabled",  # pos/eta_adapter.py::eta_settings
        "einvoice.settings_confirmed",  # pos/eta_adapter.py::eta_settings
        "einvoice.prices_include_vat",  # pos/eta_adapter.py::eta_settings
        "einvoice.default_payment_method",  # pos/eta_adapter.py::eta_settings
        "einvoice.split_payment_rule",  # pos/eta_adapter.py::eta_settings
        "einvoice.vat_category",  # pos/eta_adapter.py::eta_settings
        "einvoice.unit_code",  # pos/eta_adapter.py::eta_settings
        "einvoice.delivery_mode",  # pos/eta_adapter.py::eta_settings
        "einvoice.warn_hours_before_deadline",  # einvoice/providers/eta/delivery.py
        "einvoice.branch_code",  # pos/eta_adapter.py::eta_branch
        "einvoice.activity_code",  # pos/eta_adapter.py::eta_branch
        "einvoice.branch_governate",  # pos/eta_adapter.py::eta_branch
        "einvoice.branch_region_city",  # pos/eta_adapter.py::eta_branch
        "einvoice.branch_street",  # pos/eta_adapter.py::eta_branch
        "einvoice.branch_building_number",  # pos/eta_adapter.py::eta_branch
        "pos.take_payments",  # pos/service.py::record_sale
        "pos.allow_record_only_sales",  # pos/service.py::record_sale
        "pos.allow_sale_on_account",  # pos/service.py::record_sale
        "pos.reference_required_methods",  # pos/service.py::record_sale
        "pos.settle_payment_methods",  # pos/service.py::close_session
        "pos.variance_reason_required",  # pos/service.py::close_session
        "pos.variance_approval_threshold",  # pos/service.py::close_session
        "purchasing.allow_partial_receipt",  # purchasing/service.py::GoodsReceiptService.create
        "inventory.safety_stock_default",  # inventory/services/replenishment.py::set_policy
        "inventory.show_warehouse_transfers",  # inventory/services/screens.py::visible_screens
        "inventory.show_channel_allocation",  # inventory/services/screens.py::visible_screens
        "inventory.show_units_of_measure",  # inventory/services/screens.py::visible_screens
        "inventory.expiry_alert_days",  # inventory/services/expiry.py::expiry_report
        "inventory.dead_stock_days",  # core/dead_stock_report.py::DeadStockReportService.report
        "business.vertical",  # core/shop_type.py::choose_vertical
        "business.setup_state",  # core/activity_setup.py::read_state
        "business.type",  # core/shop_type.py::choose_vertical (derived from vertical)
        "reports.managers_see_profit",  # core/profit_report.py::_ProfitGate
        "business.terms_accepted_at",  # identity/services/auth.py::_record_signup_choices (record)
        "business.trade_name",  # pos/receipt_settings.py + pos/eta_adapter.py::_seller
        "business.legal_name",  # pos/receipt_settings.py + pos/eta_adapter.py::_seller
        "business.address.line1",  # pos/receipt_settings.py::receipt_settings
        "business.address.city",  # pos/receipt_settings.py::receipt_settings
        "business.phone",  # pos/receipt_settings.py::receipt_settings
        "business.tax_id",  # pos/receipt_settings.py + pos/eta_adapter.py::_seller
        "print.paper_width",  # pos/receipt_settings.py::receipt_settings
        "print.show_logo",  # pos/receipt_settings.py::receipt_settings
        "print.header_text",  # pos/receipt_settings.py::receipt_settings
        "print.footer_text",  # pos/receipt_settings.py::receipt_settings
        "print.copies",  # pos/receipt_settings.py::receipt_settings
        "print.show_tax_detail",  # pos/receipt_settings.py::receipt_settings
        # Phase 4–5 wiring: settings now read by the services they govern.
        "inventory.auto_reserve",  # orders/service.py::OrderService.checkout
        "inventory.fifo_enabled",  # inventory/services/valuation.py::record_sale
        "inventory.stocktake_approval_required",  # inventory/services/stocktakes.py::approve
        "purchasing.approval_required",  # purchasing/service.py::PurchaseService.create
        "purchasing.approval_threshold",  # purchasing/service.py::PurchaseService.create
        "purchasing.centralized",  # purchasing/service.py::PurchaseService.create
        "inventory.track_locations",  # inventory/services/locations.py::create_location
        "inventory.quality_check_on_receipt",  # purchasing/service.py::PurchaseService.receive
        # Phase 6–7 wiring: settings now read by the services they govern.
        "orders.reserve_on",  # orders/service.py::checkout
        "orders.allow_backorder",  # orders/service.py::checkout
        # confirm_sale, create_shipment, set_shipment_status
        "orders.deduct_stock_on",  # orders/service.py
        "notifications.low_stock_alert",  # scheduler_worker
        "notifications.order_received",  # orders/service.py
        "customer_agent.enabled",  # ai/hooks.py::maybe_auto_reply
        "customer_agent.dialect",  # ai/hooks.py (style_directive)
        "customer_agent.formality",  # ai/hooks.py (style_directive)
        "customer_agent.response_language",  # ai/hooks.py (style_directive)
        "customer_agent.handoff_enabled",  # ai/tools/support
        "customer_agent.max_turns_before_handoff",  # ai/hooks.py
        "customer_agent.show_prices",  # ai/tools/catalog
        "customer_agent.show_stock",  # ai/tools/catalog
        "analytics_agent.enabled",  # sales_intelligence agent
        "analytics_agent.min_confidence",  # sales_intelligence agent
        "analytics_agent.default_period",  # sales_intelligence agent
        "analytics_agent.include_branches",  # sales_intelligence agent
        "organization.multi_branch",  # branch service
        "organization.max_branches",  # branch service
        "branch.auto_close_shift",  # scheduler_worker
        "branch.shift_end_time",  # scheduler_worker
        "branch.notify_manager_on_variance",  # pos/service.py close_session
        "branch.allow_independent_purchasing",  # purchasing/service.py
        "catalog.sku_format",  # catalog/variants.py
        "catalog.barcode_auto_generate",  # catalog/variants.py
        "catalog.default_tax_rate",  # catalog/products.py
        "catalog.show_out_of_stock",  # ai/tools/catalog
        "catalog.max_variants_per_product",  # catalog/variants.py
        # Phase 7 wiring — Team, Security, Billing, Notifications.
        "team.require_2fa",  # identity/services/auth.py login
        "billing.auto_renew",  # billing/services/trial_expiry.py::_should_lock
        "notifications.quiet_hours_start",  # notifications/digest.py::should_send_immediately
        "notifications.quiet_hours_end",  # notifications/digest.py::should_send_immediately
        "notifications.digest_mode",  # notifications/digest.py::should_send_immediately
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

_reg(
    SettingDef(
        key="business.vertical",
        domain="business",
        type=SettingType.ENUM,
        default=DEFAULT_VERTICAL,
        scopes=(Scope.TENANT, Scope.WORKSPACE),
        allowed_values=VERTICALS,
        label_ar="قطاع النشاط",
        label_en="Industry",
        description_ar=(
            "ملابس أو صيدلية أو مطعم أو عام. يحدد القدرات المفعّلة مبدئياً وتعدّل كل واحدة منها بنفسك."
        ),
        description_en=(
            "Apparel, pharmacy, restaurant or general. It sets which capabilities "
            "start on; you can change each one."
        ),
    )
)

# Has the owner been through the first-run activity setup? The default is "done" on purpose: a shop
# that existed before the wizard has no row, so it reads "done" and is never sent to it. Only a
# signup writes "not_started", and the setup flow moves it to "done" or "skipped"
# (core/activity_setup.py is the only reader, and it is listed in ENFORCED_KEYS).
SETUP_STATES: tuple[str, ...] = ("done", "not_started", "skipped")
_reg(
    SettingDef(
        key="business.setup_state",
        domain="business",
        type=SettingType.ENUM,
        default="done",
        scopes=(Scope.TENANT,),
        allowed_values=SETUP_STATES,
        label_ar="حالة إعداد النشاط",
        label_en="Activity setup state",
        description_ar=(
            "هل أنهى المالك إعداد نشاطه أول مرة. القيمة الافتراضية «تم» فلا يُسأل أي محل قديم."
        ),
        description_en="Whether the owner finished the first-run activity setup. Defaults to done.",
    )
)

_reg(
    SettingDef(
        key="reports.managers_see_profit",
        domain="business",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="المدير يرى تقارير التكلفة والربح ويطبّق تخفيض الموسم",
        label_en="Managers see cost and profit reports and can apply a season markdown",
        description_ar=(
            "يظهر للمدير تقرير الربح والتصريف والمخزون الراكد وتخفيض الموسم. "
            "عند الإيقاف يبقى ذلك لصاحب المحل وحده. الكاشير لا يراها في الحالتين."
        ),
        description_en=(
            "A manager may open the profit, sell-through and dead-stock reports and apply a "
            "season markdown. Off leaves them to the shop owner alone. A cashier never sees them."
        ),
    )
)

# When the owner accepted the terms at signup (an ISO timestamp). Empty means it was never
# recorded: every shop that signed up before the form asked, and any client that sent no answer.
# It is a record, not a gate: nothing reads it to allow or refuse anything.
_reg(
    SettingDef(
        key="business.terms_accepted_at",
        domain="business",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        label_ar="وقت قبول الشروط",
        label_en="Terms accepted at",
        description_ar="الوقت الذي وافق فيه المالك على الشروط عند التسجيل. فارغ يعني لم يُسجَّل.",
        description_en="When the owner accepted the terms at signup. Empty means not recorded.",
    )
)

# One owner switch per capability. The vertical only chooses the starting answer (see
# ``capabilities.capability_enabled``), so the list lives in one place: capabilities.CAPABILITIES.
for _cap in CAPABILITIES.values():
    _reg(
        SettingDef(
            key=f"capability.{_cap.name}",
            domain="business",
            type=SettingType.BOOL,
            default=False,
            scopes=(Scope.TENANT, Scope.WORKSPACE),
            label_ar=_cap.label_ar,
            label_en=_cap.label_en,
            description_ar=_cap.description_ar,
            description_en=_cap.description_en,
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
        key="einvoice.eta_enabled",
        domain="einvoice",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="الإيصال الإلكتروني (مصلحة الضرائب)",
        label_en="ETA e-receipt",
        description_ar="إصدار إيصال إلكتروني لكل بيع ومرتجع من الكاشير وإرساله لمصلحة الضرائب.",
        description_en="Issue an ETA e-receipt for every cashier sale and return.",
    )
)
_reg(
    SettingDef(
        key="einvoice.settings_confirmed",
        domain="einvoice",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="راجعت إعدادات الأسعار والضريبة والدفع وأكّدتها",
        label_en="I reviewed the price, VAT and payment settings",
        description_ar=(
            "الأسعار شاملة الضريبة أو لا، وفئة الضريبة، وطريقة الدفع الاحتياطية بتختلف من محل "
            "لمحل. القيم الأولية مجرد اقتراح، ولن يصدر أي إيصال قبل ما تراجعها وتؤكد."
        ),
        description_en=(
            "Whether prices include VAT, the VAT category and the fallback payment method differ "
            "from shop to shop. The starting values are suggestions: no receipt is issued until "
            "you confirm them."
        ),
    )
)
_reg(
    SettingDef(
        key="einvoice.prices_include_vat",
        domain="einvoice",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="الأسعار شاملة ضريبة القيمة المضافة",
        label_en="Prices include VAT",
        description_ar="لو مفعّل فسعر الصنف المسجّل في الكاشير يشمل الضريبة، وتُستخرج منه في الإيصال.",
        description_en="Recorded prices already include VAT; it is extracted on the receipt.",
    )
)
_reg(
    SettingDef(
        key="einvoice.default_payment_method",
        domain="einvoice",
        type=SettingType.ENUM,
        default="C",
        scopes=(Scope.TENANT,),
        allowed_values=("C", "V", "CC", "VC", "VO", "PR", "GC", "P", "O"),
        label_ar="طريقة الدفع الافتراضية في الإيصال",
        label_en="Default receipt payment method",
        description_ar=(
            "تُستخدم فقط لو البيع ما سجّل طريقة دفع (بيع على الحساب، أو كاشير لا يستلم نقودًا)."
        ),
        description_en=(
            "Used only when the sale recorded no payment (on account, or a till that takes none)."
        ),
    )
)
_reg(
    SettingDef(
        key="einvoice.split_payment_rule",
        domain="einvoice",
        type=SettingType.ENUM,
        default="largest",
        scopes=(Scope.TENANT,),
        allowed_values=("largest", "cash_first"),
        label_ar="قاعدة الدفع المقسّم في الإيصال",
        label_en="Split-payment rule on the receipt",
        description_ar=(
            "الإيصال بيقبل طريقة دفع واحدة. لو العميل دفع بأكتر من طريقة: "
            "الأكبر مبلغًا، أو نقدي لو فيه أي مبلغ نقدي."
        ),
        description_en=(
            "A receipt carries one payment method. When a sale is split: the method that took "
            "the most money, or cash whenever any cash was taken."
        ),
    )
)
_reg(
    SettingDef(
        key="einvoice.vat_category",
        domain="einvoice",
        type=SettingType.ENUM,
        default="taxable",
        scopes=(Scope.TENANT,),
        allowed_values=("taxable", "exempt", "non_taxable"),
        label_ar="فئة ضريبة القيمة المضافة للأصناف",
        label_en="Item VAT category",
        description_ar="خاضع للضريبة، معفى، أو غير خاضع. تُطبّق على كل أصناف المحل.",
        description_en="Taxable, exempt or non-taxable; applied to every item of the store.",
    )
)
_reg(
    SettingDef(
        key="einvoice.unit_code",
        domain="einvoice",
        type=SettingType.STRING,
        default="EA",
        scopes=(Scope.TENANT,),
        max_length=10,
        label_ar="وحدة القياس في الإيصال",
        label_en="Receipt unit of measure",
        description_ar="كود وحدة القياس المعتمد لدى المصلحة. القطعة EA.",
        description_en="Authority unit code. A piece is EA.",
    )
)
_reg(
    SettingDef(
        key="einvoice.delivery_mode",
        domain="einvoice",
        type=SettingType.ENUM,
        default="FC",
        scopes=(Scope.TENANT,),
        allowed_values=("FC", "TO", "TC"),
        label_ar="وضع التسليم",
        label_en="Delivery mode",
        description_ar="FC من مكان الشركة، TO نقل بواسطة آخرين، TC نقل بواسطة الشركة.",
        description_en="FC from the company, TO transport by others, TC transport by the company.",
    )
)
_reg(
    SettingDef(
        key="einvoice.warn_hours_before_deadline",
        domain="einvoice",
        type=SettingType.NUMBER,
        default=24,
        scopes=(Scope.TENANT,),
        min_value=1,
        max_value=96,
        label_ar="التنبيه قبل انتهاء مهلة الإرسال (ساعات)",
        label_en="Warn before send deadline (hours)",
        description_ar="كم ساعة قبل انتهاء مهلة إرسال الإيصال تظهر لك تنبيهًا.",
        description_en="How many hours before a receipt's send deadline you are warned.",
    )
)
_reg(
    SettingDef(
        key="einvoice.branch_code",
        domain="einvoice",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=120,
        label_ar="كود الفرع لدى المصلحة",
        label_en="Branch code at the authority",
        description_ar="الكود المسجل لفرعك في بوابة الممول (رقم، وليس اسم الفرع).",
        description_en="The number registered for your branch in the taxpayer portal.",
    )
)
_reg(
    SettingDef(
        key="einvoice.activity_code",
        domain="einvoice",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=120,
        label_ar="كود النشاط",
        label_en="Activity code",
        description_ar="كود نشاطك المسجل، مثل 4771 لمتاجر الملابس.",
        description_en="Your registered activity code, e.g. 4771 for clothing stores.",
    )
)
_reg(
    SettingDef(
        key="einvoice.branch_governate",
        domain="einvoice",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=120,
        label_ar="محافظة الفرع",
        label_en="Branch governorate",
        description_ar="محافظة الفرع كما هي مسجلة.",
        description_en="Branch governorate as registered.",
    )
)
_reg(
    SettingDef(
        key="einvoice.branch_region_city",
        domain="einvoice",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=120,
        label_ar="المدينة أو المنطقة",
        label_en="Branch city or region",
        description_ar="مدينة أو منطقة الفرع كما هي مسجلة.",
        description_en="Branch city or region as registered.",
    )
)
_reg(
    SettingDef(
        key="einvoice.branch_street",
        domain="einvoice",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=120,
        label_ar="شارع الفرع",
        label_en="Branch street",
        description_ar="شارع الفرع كما هو مسجل.",
        description_en="Branch street as registered.",
    )
)
_reg(
    SettingDef(
        key="einvoice.branch_building_number",
        domain="einvoice",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=120,
        label_ar="رقم المبنى",
        label_en="Branch building number",
        description_ar="رقم مبنى الفرع كما هو مسجل.",
        description_en="Branch building number as registered.",
    )
)
_reg(
    SettingDef(
        key="pos.cash_movement_limit",
        domain="pos",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT, Scope.BRANCH),
        min_value=0,
        max_value=1_000_000,
        label_ar="سقف حركة النقدية",
        label_en="Cash movement limit",
        description_ar=(
            "أقصى مبلغ مسموح في حركة واحدة على الدرج (إيداع أو سحب). صفر يعني بلا سقف."
        ),
        description_en=(
            "The largest single drawer movement (pay-in or pay-out) a cashier may record. "
            "Zero means no limit."
        ),
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
        key="pos.refund_cash_only",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH),
        branch_delegable=True,
        label_ar="رد الفلوس نقدي فقط",
        label_en="Refund Cash Only",
        description_ar=(
            "لما يكون مفتوح، الكاشير مبيعلنش رد بطاقة أو محفظة من النظام: المبلغ بيظهر كتنبيه "
            "يرده على الماكينة بإيده، ومفيش سطر استرداد بيتسجل. مناسب للمحلات اللي بتبدأ نقدي."
        ),
        description_en=(
            "When on, the till never records a card/wallet reversal: that amount is reported for "
            "the cashier to reverse on the terminal by hand. Right for shops starting cash-only."
        ),
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
        key="pos.allow_record_only_sales",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="السماح بالبيع دون تحصيل",
        label_en="Allow Selling Without Collecting",
        description_ar=(
            "محل الملابس الذي لم يكمل إعداد النشاط يبيع دون تسجيل أي وسيلة دفع، فلا يدخل أي مبلغ "
            "في الدرج ولا في الحسابات. هذا الخيار هو الموافقة الصريحة على العمل بهذه الطريقة. "
            "بدونه يوقف النظام البيع ويطلب إنهاء إعداد التحصيل."
        ),
        description_en=(
            "An apparel shop that skipped its setup would sell without recording any payment, so "
            "no money reaches the drawer or the books. This switch is the explicit yes to running "
            "that way. Without it the till refuses the sale and asks for the collection setup."
        ),
    )
)
_reg(
    SettingDef(
        key="pos.settle_payment_methods",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="تسوية كل وسائل الدفع عند الإغلاق",
        label_en="Settle Every Payment Method at Close",
        description_ar=(
            "عند التفعيل يطلب إغلاق الوردية عدّاً فعلياً لكل وسيلة دفع استُخدمت (الكارت، المحفظة، "
            "التحويل) لا للكاش وحده، ويحفظ المتوقع والفعلي والفرق لكل وسيلة. بدونها تُقارن "
            "الوسائل غير النقدية على الشاشة فقط ولا يُحفظ فرقها."
        ),
        description_en=(
            "When on, closing the shift requires a real count for every payment method the day "
            "used (card, wallet, transfer), not just cash, and stores expected vs counted vs the "
            "difference per method. When off, non-cash methods are shown but not settled."
        ),
    )
)
_reg(
    SettingDef(
        key="pos.allow_sale_on_account",
        domain="pos",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="البيع بالآجل على حساب العميل",
        label_en="Sell on Customer Account",
        description_ar=(
            "عند التفعيل يستطيع الكاشير تسجيل جزء من البيع (أو كله) على حساب عميل له حساب آجل "
            "وحد ائتمان. لا يعمل إلا مع تسجيل وسائل الدفع، ويلزم تحديد العميل صراحة."
        ),
        description_en=(
            "When on, the cashier can put part or all of a sale on the account of a customer who "
            "has a credit account and limit. Needs payments recording, and a named customer."
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
_reg(
    SettingDef(
        key="pos.variance_reason_required",
        domain="pos",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="سبب الفرق إجباري عند إغلاق الدرج",
        label_en="Require a Reason for a Drawer Variance",
        description_ar=(
            "عند التفعيل لا يُقفل الدرج إذا كان المعدود يختلف عن المتوقع إلا بكتابة سبب الفرق. "
            "يعمل فقط حيث يُسجَّل الدفع ويُعدّ الدرج."
        ),
        description_en=(
            "When on, a drawer whose count differs from the expected cash cannot close without a "
            "written reason. Applies only where the till takes payments and counts its drawer."
        ),
    )
)
# الباب القديم للاستيراد (/imports/products، CSV صف واحد = منتج + تركيبة واحدة) اتقفل نهائيًا
# للتاجر: مركز الاستيراد هو المسار الوحيد. المفتاح هنا بدل حذف الكود — تشغيله يرجّع الباب
# للعمل، بس حتى وهو مفتوح بيدخل على نفس مسار مركز الاستيراد مش على قواعده القديمة.
_reg(
    SettingDef(
        key="imports.legacy_csv_endpoint",
        domain="imports",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        audit=True,
        label_ar="فتح مسار الاستيراد القديم (CSV مباشر)",
        label_en="Re-open the legacy CSV import endpoint",
        description_ar=(
            "مقفول افتراضيًا: التاجر بيستورد من مركز الاستيراد بس، عشان كل ملف يمشي على نفس "
            "الحقول والقواعد. تشغيله يرجّع /imports/products للعمل، ولو رجع بيمشي على نفس مسار "
            "مركز الاستيراد: الملف بيتحول جلسة استيراد عادية بدل ما يتحفظ بقواعد تانية."
        ),
        description_en=(
            "Off by default: the Import Center is the one way in, so every file follows the same "
            "fields and rules. Turning it on re-opens /imports/products, and even then the file "
            "becomes an ordinary import session instead of being applied under the old rules."
        ),
    )
)
_reg(
    SettingDef(
        key="pos.variance_approval_threshold",
        domain="pos",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT, Scope.BRANCH, Scope.POS_PROFILE),
        min_value=0,
        max_value=1_000_000,
        audit=True,
        branch_delegable=False,
        segments=("retail",),
        label_ar="حدّ فرق الدرج الذي يحتاج موافقة مدير",
        label_en="Drawer Variance That Needs a Manager",
        description_ar=(
            "فرق أكبر من هذا المبلغ (عجزاً أو زيادة) لا يُقفل الدرج معه إلا بموافقة من يملك "
            "صلاحية المدير، ويُسجَّل اسمه ووقت الموافقة. صفر يعني لا حدّ."
        ),
        description_en=(
            "A drawer variance larger than this amount (short or over) can only close with a "
            "manager's approval, recorded with their name and time. Zero means no limit."
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
        key="inventory.expiry_alert_days",
        domain="inventory",
        type=SettingType.NUMBER,
        default=30,
        scopes=(Scope.TENANT,),
        min_value=1,
        max_value=730,
        label_ar="تنبيه قرب الانتهاء (أيام)",
        label_en="Expiry alert window (days)",
        description_ar="الدفعة التي تنتهي صلاحيتها خلال هذه المدة تظهر في تقرير قرب الانتهاء.",
        description_en="A batch that expires within this many days appears in the expiry report.",
    )
)
_reg(
    SettingDef(
        key="inventory.dead_stock_days",
        domain="inventory",
        type=SettingType.NUMBER,
        default=60,
        scopes=(Scope.TENANT,),
        min_value=7,
        max_value=730,
        label_ar="اعتبار الصنف راكد بعد (أيام بلا بيع)",
        label_en="Dead stock after (days without a sale)",
        description_ar="الصنف الذي له رصيد ولم يُبَع خلال هذه المدة يظهر في تقرير المخزون الراكد.",
        description_en=(
            "A variant with stock and no sale within this many days appears in the "
            "dead-stock report."
        ),
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
        key="inventory.show_warehouse_transfers",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="إظهار التحويلات بين المخازن",
        label_en="Show transfers between warehouses",
        description_ar=(
            "يُظهر شاشة تحويل البضاعة بين المخازن. أطفئه لمحل بمخزن واحد. لا يحذف أي بيانات."
        ),
        description_en=(
            "Shows the screen for moving stock between warehouses. "
            "Turn off for a one-store shop. Deletes no data."
        ),
    )
)
_reg(
    SettingDef(
        key="inventory.show_channel_allocation",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="إظهار تخصيص المخزون للبيع أونلاين",
        label_en="Show online stock allocation",
        description_ar=(
            "يُظهر شاشة تخصيص كميات للبيع عبر القنوات الإلكترونية. "
            "أطفئه لمحل بيع مباشر فقط. لا يحذف أي بيانات."
        ),
        description_en=(
            "Shows the screen that reserves quantities for online channels. "
            "Turn off for a walk-in-only shop. Deletes no data."
        ),
    )
)
_reg(
    SettingDef(
        key="inventory.show_units_of_measure",
        domain="inventory",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="إظهار وحدات القياس",
        label_en="Show units of measure",
        description_ar=(
            "يُظهر اختيار وحدة القياس وتحويلها (كرتونة، دستة). "
            "أطفئه لمحل يبيع بالقطعة فقط. لا يحذف أي بيانات."
        ),
        description_en=(
            "Shows unit-of-measure choice and conversion (carton, dozen). "
            "Turn off for a shop that sells by the piece only. Deletes no data."
        ),
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

# ======================== CUSTOMER AGENT (§49) ============================
#
# Customer Agent answers customer questions on WhatsApp, Messenger, web chat.
# These settings control its identity, response rules, knowledge sources,
# human handoff, and safety — NOT its tool capabilities (those are in the
# agent's tool definitions, never in settings).

_reg(
    SettingDef(
        key="customer_agent.enabled",
        domain="customer_agent",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="تفعيل وكيل خدمة العملاء",
        label_en="Customer Agent Enabled",
        description_ar="تفعيل الرد التلقائي على رسائل العملاء عبر القنوات.",
        description_en="Enable automated replies to customer messages across channels.",
    )
)
_reg(
    SettingDef(
        key="customer_agent.dialect",
        domain="customer_agent",
        type=SettingType.ENUM,
        default="egyptian",
        scopes=(Scope.TENANT,),
        allowed_values=("msa", "egyptian", "gulf", "levantine"),
        label_ar="لهجة الرد",
        label_en="Response Dialect",
        description_ar="اللهجة التي يستخدمها الوكيل في الرد على العملاء.",
        description_en="The dialect the agent uses when replying to customers.",
    )
)
_reg(
    SettingDef(
        key="customer_agent.formality",
        domain="customer_agent",
        type=SettingType.ENUM,
        default="friendly",
        scopes=(Scope.TENANT,),
        allowed_values=("formal", "friendly", "casual"),
        label_ar="درجة الرسمية",
        label_en="Formality Level",
        description_ar="مستوى الرسمية في ردود الوكيل.",
        description_en="How formal the agent's replies are.",
    )
)
_reg(
    SettingDef(
        key="customer_agent.response_language",
        domain="customer_agent",
        type=SettingType.ENUM,
        default="ar",
        scopes=(Scope.TENANT,),
        allowed_values=("ar", "en", "auto"),
        label_ar="لغة الرد",
        label_en="Response Language",
        description_ar="لغة الرد على العملاء: عربي، إنجليزي، أو تلقائي حسب رسالتهم.",
        description_en=(
            "Reply language: Arabic, English, or auto-detect from the customer's message."
        ),
    )
)
_reg(
    SettingDef(
        key="customer_agent.handoff_enabled",
        domain="customer_agent",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="التحويل لموظف",
        label_en="Human Handoff",
        description_ar="السماح بتحويل المحادثة لموظف بشري عند الحاجة.",
        description_en="Allow the agent to hand a conversation to a human staff member.",
    )
)
_reg(
    SettingDef(
        key="customer_agent.max_turns_before_handoff",
        domain="customer_agent",
        type=SettingType.NUMBER,
        default=5,
        scopes=(Scope.TENANT,),
        min_value=1,
        max_value=50,
        label_ar="أقصى عدد رسائل قبل التحويل",
        label_en="Max Turns Before Handoff",
        description_ar="بعد هذا العدد من تبادل الرسائل دون حل، يحوّل الوكيل المحادثة لموظف.",
        description_en="After this many message exchanges without resolution, the agent hands off.",
    )
)
_reg(
    SettingDef(
        key="customer_agent.show_prices",
        domain="customer_agent",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="إظهار الأسعار",
        label_en="Show Prices",
        description_ar="هل يجيب الوكيل عن أسعار المنتجات عند السؤال عنها؟",
        description_en="Whether the agent answers product price questions.",
    )
)
_reg(
    SettingDef(
        key="customer_agent.show_stock",
        domain="customer_agent",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="إظهار المخزون",
        label_en="Show Stock",
        description_ar="هل يجيب الوكيل عن توفر المنتجات في المخزون؟",
        description_en="Whether the agent answers product availability questions.",
    )
)

# ====================== ANALYTICS AGENT (§50) =============================
#
# Analytics Agent answers the owner's business questions (sales, margins,
# inventory health). These settings control its data access, metrics, and
# recommendation behaviour. The LLM explains numbers the engine computes;
# it never invents calculations or runs free SQL.

_reg(
    SettingDef(
        key="analytics_agent.enabled",
        domain="analytics_agent",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="تفعيل وكيل التحليلات",
        label_en="Analytics Agent Enabled",
        description_ar="تفعيل الإجابة على أسئلة المالك حول المبيعات والأداء.",
        description_en="Enable answering the owner's questions about sales and performance.",
    )
)
_reg(
    SettingDef(
        key="analytics_agent.default_period",
        domain="analytics_agent",
        type=SettingType.ENUM,
        default="30d",
        scopes=(Scope.TENANT,),
        allowed_values=("7d", "30d", "90d", "ytd", "all"),
        label_ar="الفترة الافتراضية",
        label_en="Default Period",
        description_ar="الفترة الزمنية الافتراضية للتقارير عند عدم تحديدها.",
        description_en="Default time range for reports when none is specified.",
    )
)
_reg(
    SettingDef(
        key="analytics_agent.include_branches",
        domain="analytics_agent",
        type=SettingType.LIST,
        default=[],
        scopes=(Scope.TENANT,),
        label_ar="الفروع المشمولة",
        label_en="Included Branches",
        description_ar="قائمة معرفات الفروع التي يحق للوكيل تحليل بياناتها. فارغة = جميع الفروع.",
        description_en="Branch IDs the agent may analyse. Empty = all branches.",
    )
)
_reg(
    SettingDef(
        key="analytics_agent.min_confidence",
        domain="analytics_agent",
        type=SettingType.NUMBER,
        default=0.7,
        scopes=(Scope.TENANT,),
        min_value=0.0,
        max_value=1.0,
        label_ar="الحد الأدنى للثقة",
        label_en="Minimum Confidence",
        description_ar="أدنى مستوى ثقة لتقديم توصية. أقل من ذلك يُعرض كاقتراح فقط.",
        description_en=(
            "Minimum confidence to present a recommendation. Below this, it is a suggestion only."
        ),
    )
)

# ======================== ORGANIZATION (§47 Phase 4) ======================
#
# Organization-level settings that govern the account as a whole: its calendar, its branch
# structure, and its defaults.  These are distinct from the tenant table columns (name,
# currency, timezone, dialect, country) which remain the domain of ``TenantSettingsService``.
# The settings here are configuration the tenant table does not carry.

_reg(
    SettingDef(
        key="organization.fiscal_year_start_month",
        domain="organization",
        type=SettingType.NUMBER,
        default=1,
        scopes=(Scope.TENANT,),
        min_value=1,
        max_value=12,
        label_ar="بداية السنة المالية (شهر)",
        label_en="Fiscal Year Start Month",
        description_ar="الشهر الذي تبدأ فيه السنة المالية (1–12). يُستخدم في التقارير السنوية.",
        description_en="The month the fiscal year starts (1–12). Used in annual reports.",
    )
)
_reg(
    SettingDef(
        key="organization.multi_branch",
        domain="organization",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="تشغيل متعدد الفروع",
        label_en="Multi-Branch Operations",
        description_ar="تفعيل إدارة عدة فروع تحت نفس المنشأة. يفتح شاشات الفروع والتحويلات.",
        description_en="Enable managing multiple branches under one account. Opens branch screens.",
    )
)
_reg(
    SettingDef(
        key="organization.max_branches",
        domain="organization",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT,),
        min_value=0,
        max_value=1000,
        label_ar="الحد الأقصى للفروع",
        label_en="Maximum Branches",
        description_ar="أقصى عدد فروع مسموح. صفر يعني بلا حد.",
        description_en="The maximum number of branches allowed. Zero means no limit.",
    )
)
_reg(
    SettingDef(
        key="organization.default_language",
        domain="organization",
        type=SettingType.ENUM,
        default="ar",
        scopes=(Scope.TENANT,),
        allowed_values=("ar", "en"),
        label_ar="اللغة الافتراضية",
        label_en="Default Language",
        description_ar="اللغة الافتراضية لواجهة المنشأة للموظفين الجدد.",
        description_en="The default UI language for new staff members.",
    )
)
_reg(
    SettingDef(
        key="organization.brand_color",
        domain="organization",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=7,
        label_ar="لون العلامة التجارية",
        label_en="Brand Color",
        description_ar="لون رئيسي للعلامة (كود HEX مثل #2563EB). يظهر في الواجهة والإيصالات.",
        description_en="A primary brand color (HEX, e.g. #2563EB). Shown in the UI and receipts.",
    )
)

# ============================== BRANCH (§47 Phase 4) ======================
#
# Branch-level operational settings. These let each branch run differently from the
# tenant default without touching the tenant-level value. The scope_graph walks
# branch → workspace → tenant, so a branch override only affects that one branch.

_reg(
    SettingDef(
        key="branch.auto_close_shift",
        domain="branch",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH),
        branch_delegable=True,
        label_ar="إغلاق الوردية تلقائياً",
        label_en="Auto-Close Shift",
        description_ar="إغلاق وردية الكاشير تلقائياً في نهاية اليوم إذا لم يُغلقها الكاشير.",
        description_en="Auto-close the cashier shift at end of day if the cashier did not.",
    )
)
_reg(
    SettingDef(
        key="branch.shift_end_time",
        domain="branch",
        type=SettingType.STRING,
        default="23:59",
        scopes=(Scope.TENANT, Scope.BRANCH),
        max_length=5,
        branch_delegable=True,
        label_ar="وقت نهاية الوردية",
        label_en="Shift End Time",
        description_ar="الوقت الذي تُغلق عنده الوردية تلقائياً (بصيغة 24 ساعة HH:MM).",
        description_en="The time at which the shift auto-closes (24-hour format HH:MM).",
    )
)
_reg(
    SettingDef(
        key="branch.notify_manager_on_variance",
        domain="branch",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT, Scope.BRANCH),
        branch_delegable=True,
        label_ar="إشعار المدير بفرق الدرج",
        label_en="Notify Manager on Drawer Variance",
        description_ar="إرسال إشعار للمدير عند وجود فرق في درج الكاشير عند الإغلاق.",
        description_en="Notify the manager when a drawer variance is found at close.",
    )
)
_reg(
    SettingDef(
        key="branch.allow_independent_purchasing",
        domain="branch",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT, Scope.BRANCH),
        branch_delegable=True,
        label_ar="شراء مستقل للفرع",
        label_en="Independent Branch Purchasing",
        description_ar="السماح للفرع بإنشاء أوامر شراء خاصة به دون الرجوع للإدارة المركزية.",
        description_en="Allow a branch to create its own purchase orders without central approval.",
    )
)

# ============================== CATALOG (§47 Phase 5) ======================
#
# Catalog-level settings that control how products are created, coded and displayed.
# The catalog module reads these to decide SKU generation, barcode rules and defaults.

_reg(
    SettingDef(
        key="catalog.sku_format",
        domain="catalog",
        type=SettingType.STRING,
        default="{category}-{number}",
        scopes=(Scope.TENANT,),
        max_length=127,
        label_ar="صيغة رمز المنتج (SKU)",
        label_en="SKU Format",
        description_ar=(
            "نمط توليد رمز المنتج. {category} يُعوّض بتصنيف المنتج، و{number} برقم تسلسلي تلقائي."
        ),
        description_en=(
            "Pattern for generating product codes. {category} is replaced by the product category, "
            "{number} by an auto-incremented number."
        ),
    )
)
_reg(
    SettingDef(
        key="catalog.barcode_auto_generate",
        domain="catalog",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="توليد الباركود تلقائياً",
        label_en="Auto-Generate Barcodes",
        description_ar="توليد باركود تلقائي للمنتجات التي لم يُدخل لها باركود يدوي.",
        description_en="Auto-generate a barcode for products without a manually entered one.",
    )
)
_reg(
    SettingDef(
        key="catalog.default_tax_rate",
        domain="catalog",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT,),
        min_value=0,
        max_value=100,
        label_ar="نسبة الضريبة الافتراضية %",
        label_en="Default Tax Rate %",
        description_ar="نسبة الضريبة الافتراضية للمنتجات الجديدة (0 يعني لا ضريبة).",
        description_en="The default tax rate for new products (0 means no tax).",
    )
)
_reg(
    SettingDef(
        key="catalog.show_out_of_stock",
        domain="catalog",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="إظهار المنتجات غير المتوفرة",
        label_en="Show Out-of-Stock Items",
        description_ar="إظهار المنتجات التي رصيدها صفر في الكتالوج والكاشير.",
        description_en="Show products with zero stock in the catalog and cashier.",
    )
)
_reg(
    SettingDef(
        key="catalog.max_variants_per_product",
        domain="catalog",
        type=SettingType.NUMBER,
        default=100,
        scopes=(Scope.TENANT,),
        min_value=1,
        max_value=10000,
        label_ar="الحد الأقصى للمتغيرات لكل منتج",
        label_en="Max Variants Per Product",
        description_ar="أقصى عدد متغيرات (مقاس/لون) يمكن إضافتها لمنتج واحد.",
        description_en="The maximum number of variants (size/colour) a single product can have.",
    )
)

# ============================== TEAM (§117 Phase 7) ========================
#
# Team-level settings controlling how new members join and how sessions behave.

_reg(
    SettingDef(
        key="team.default_role",
        domain="team",
        type=SettingType.ENUM,
        default="cashier",
        scopes=(Scope.TENANT,),
        allowed_values=("cashier", "manager", "admin"),
        label_ar="دور العضو الجديد الافتراضي",
        label_en="Default Role for New Members",
        description_ar="الدور الذي يُسند تلقائياً لعضو فريق جديد عند دعوته.",
        description_en="The role assigned automatically to a new team member when invited.",
    )
)
_reg(
    SettingDef(
        key="team.require_2fa",
        domain="team",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        audit=True,
        sensitivity=Sensitivity.SENSITIVE,
        label_ar="إلزام المصادقة الثنائية لكل الأعضاء",
        label_en="Require 2FA for All Members",
        description_ar="فرض تفعيل المصادقة الثنائية على كل أعضاء الفريق قبل تسجيل الدخول.",
        description_en="Force every team member to enable 2FA before signing in.",
    )
)
_reg(
    SettingDef(
        key="team.session_timeout_minutes",
        domain="team",
        type=SettingType.NUMBER,
        default=0,
        scopes=(Scope.TENANT,),
        min_value=0,
        max_value=10080,
        label_ar="مدة انتهاء الجلسة (دقائق)",
        label_en="Session Timeout (Minutes)",
        description_ar="مدة بقاء جلسة الموظف نشطة قبل أن تُسأل لإعادة الدخول. صفر يعني بلا حد.",
        description_en=(
            "How many minutes a staff session stays active before a re-login is required. "
            "Zero means no limit."
        ),
    )
)
_reg(
    SettingDef(
        key="team.allow_member_invites",
        domain="team",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="السماح بدعوة أعضاء",
        label_en="Allow Member Invites",
        description_ar="السماح للمدير بدعوة أعضاء جدد للفريق عبر البريد الإلكتروني.",
        description_en="Allow managers to invite new team members by email.",
    )
)

# ============================= SECURITY (§67-69) ===========================
#
# Security policies that protect the account: password rules, API key lifecycle,
# and audit retention. These are tenant-level and sensitive.

_reg(
    SettingDef(
        key="security.require_strong_passwords",
        domain="security",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        audit=True,
        sensitivity=Sensitivity.SENSITIVE,
        label_ar="إلزام كلمات مرور قوية",
        label_en="Require Strong Passwords",
        description_ar="فرض كلمات مرور قوية (8 أحرف على الأقل، أرقام وحروف) عند التسجيل والتعيين.",
        description_en=(
            "Enforce strong passwords (at least 8 characters, with numbers and letters) on "
            "registration and password reset."
        ),
    )
)
_reg(
    SettingDef(
        key="security.api_key_rotation_days",
        domain="security",
        type=SettingType.NUMBER,
        default=90,
        scopes=(Scope.TENANT,),
        min_value=0,
        max_value=365,
        audit=True,
        sensitivity=Sensitivity.SENSITIVE,
        label_ar="مدة تدوير مفاتيح API (أيام)",
        label_en="API Key Rotation Period (Days)",
        description_ar=("عدد الأيام قبل أن يطلب النظام تدوير مفتاح API. صفر يعني لا تدوير إلزامي."),
        description_en=(
            "Days before the system asks to rotate an API key. Zero means no forced rotation."
        ),
    )
)
_reg(
    SettingDef(
        key="security.audit_retention_days",
        domain="security",
        type=SettingType.NUMBER,
        default=365,
        scopes=(Scope.TENANT,),
        min_value=30,
        max_value=2555,
        label_ar="مدة الاحتفاظ بسجل التدقيق (أيام)",
        label_en="Audit Log Retention (Days)",
        description_ar="كم يوماً تُحفظ فيه سجلات التدقيق قبل أن تُؤرشف أو تُحذف.",
        description_en="How many days audit logs are kept before they are archived or deleted.",
    )
)
_reg(
    SettingDef(
        key="security.ip_allowlist",
        domain="security",
        type=SettingType.LIST,
        default=[],
        scopes=(Scope.TENANT,),
        sensitivity=Sensitivity.SENSITIVE,
        label_ar="قائمة IPs المسموح بها",
        label_en="IP Allowlist",
        description_ar="قائمة عناوين IP المسموح لها بالوصول. فارغة تعني السماح للجميع.",
        description_en="List of IP addresses allowed to access the account. Empty = allow all.",
    )
)

# ============================== BILLING (§53-54) ===========================
#
# Billing preferences that control subscription renewal, currency, and
# renewal reminders. The billing service reads these to decide behaviour.

_reg(
    SettingDef(
        key="billing.auto_renew",
        domain="billing",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        audit=True,
        label_ar="التجديد التلقائي للاشتراك",
        label_en="Auto-Renew Subscription",
        description_ar="تجديد الاشتراك تلقائياً عند انتهاء الفترة الحالية.",
        description_en="Automatically renew the subscription when the current period ends.",
    )
)
_reg(
    SettingDef(
        key="billing.currency",
        domain="billing",
        type=SettingType.ENUM,
        default="EGP",
        scopes=(Scope.TENANT,),
        allowed_values=("EGP", "USD", "SAR", "AED"),
        label_ar="عملة الفوترة",
        label_en="Billing Currency",
        description_ar="العملة المستخدمة في الفواتير والمدفوعات.",
        description_en="The currency used for invoices and payments.",
    )
)
_reg(
    SettingDef(
        key="billing.notify_before_renewal_days",
        domain="billing",
        type=SettingType.NUMBER,
        default=7,
        scopes=(Scope.TENANT,),
        min_value=0,
        max_value=30,
        label_ar="تنبيه قبل التجديد (أيام)",
        label_en="Notify Before Renewal (Days)",
        description_ar="كم يوماً قبل تجديد الاشتراك يُرسل تنبيه. صفر يعني لا تنبيه.",
        description_en="Days before subscription renewal to send a reminder. Zero = no reminder.",
    )
)

# ==================== NOTIFICATIONS (expanded, §166) =======================

_reg(
    SettingDef(
        key="notifications.quiet_hours_start",
        domain="notifications",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=5,
        label_ar="بداية ساعات الهدوء",
        label_en="Quiet Hours Start",
        description_ar="الوقت الذي يبدأ عنده كتم الإشعارات (بصيغة 24 ساعة HH:MM).",
        description_en="Time from which notifications are muted (24-hour HH:MM). Empty = none.",
    )
)
_reg(
    SettingDef(
        key="notifications.quiet_hours_end",
        domain="notifications",
        type=SettingType.STRING,
        default="",
        scopes=(Scope.TENANT,),
        max_length=5,
        label_ar="نهاية ساعات الهدوء",
        label_en="Quiet Hours End",
        description_ar="الوقت الذي ينتهي عنده كتم الإشعارات (بصيغة 24 ساعة HH:MM).",
        description_en="Time at which notification muting ends (24-hour HH:MM).",
    )
)
_reg(
    SettingDef(
        key="notifications.digest_mode",
        domain="notifications",
        type=SettingType.ENUM,
        default="realtime",
        scopes=(Scope.TENANT,),
        allowed_values=("realtime", "hourly", "daily"),
        label_ar="وضع تجميع الإشعارات",
        label_en="Notification Digest Mode",
        description_ar="كيف تُرسل الإشعارات: فورية، مجمّعة كل ساعة، أو يومية.",
        description_en="How notifications arrive: instantly, hourly, or daily digest.",
    )
)
_reg(
    SettingDef(
        key="notifications.email_enabled",
        domain="notifications",
        type=SettingType.BOOL,
        default=False,
        scopes=(Scope.TENANT,),
        label_ar="إشعارات البريد الإلكتروني",
        label_en="Email Notifications",
        description_ar="إرسال الإشعارات عبر البريد الإلكتروني بالإضافة للإشعار داخل التطبيق.",
        description_en="Send notifications by email in addition to in-app alerts.",
    )
)
_reg(
    SettingDef(
        key="notifications.push_enabled",
        domain="notifications",
        type=SettingType.BOOL,
        default=True,
        scopes=(Scope.TENANT,),
        label_ar="الإشعارات الفورية (Push)",
        label_en="Push Notifications",
        description_ar="إرسال إشعارات push للمتصفح والجوال.",
        description_en="Send push notifications to browser and mobile.",
    )
)

# ======================== NOTIFICATIONS (existing, continued) =============

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
