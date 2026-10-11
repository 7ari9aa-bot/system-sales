"""Agent Definition — Customer.

Registers the ``customer`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""

from __future__ import annotations

from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

# REPLY-ONLY (review P0-2): the customer agent answers and looks things up —
# it never mutates state. Orders, tasks and tags are handled by human staff
# via handover; the commerce tools stay implemented in tools.py but are NOT
# authorized for this kind (the runtime refuses them even if a stale row
# flips back on, and the sync quarantine disables the rows).
CUSTOMER_TOOLS = [
    "search_products",
    "get_variant_price",
    "check_stock",
    "get_customer",
    "get_order",
    "search_knowledge",
    "find_product_by_image",
    "resolve_product_media",
]

CUSTOMER_SYSTEM_PROMPT = (
    "أنت مساعد خدمة العملاء والمبيعات الذكي للمتجر. تتحدث بلهجة مصرية مهذبة وودودة ومباشرة.\n"
    "مهمتك مساعدة العملاء في الاستفسار عن المنتجات، الأسعار، المخزون، وحالة الطلبات، وإتمام "
    "عمليات الشراء.\n"
    "القواعد الإلزامية:\n"
    "1. لا تذكر أو تؤكد أي سعر أو كمية متوفرة إلا بعد الاستعلام عنها عبر الأدوات المخصصة.\n"
    "2. قبل تسجيل أي طلب، تأكد من وضوح كافة بيانات العميل والمنتج والكمية.\n"
    "3. التزم بسياسات المتجر المعلنة بدقة (الشحن، الدفع، الاسترجاع والاستبدال).\n"
    "4. إذا طلب العميل التحدث مع موظف خدمة عملاء أو واجهت طلباً لا تستطيع حله، حوّل "
    "المحادثة لموظف بشري بلطف."
)

_DEFINITION = AgentDefinition(
    kind="customer",
    name="Customer Service Agent",
    description=(
        "Handles customer inquiries, catalog search, order status, and "
        "vision-based product matching. Reply-only: orders and record "
        "changes are handled by human staff."
    ),
    capabilities=[
        AgentCapability(
            name="get_customer", description="Read current customer profile", required=True
        ),
        AgentCapability(name="get_order", description="Read customer order details", required=True),
        AgentCapability(
            name="search_products", description="Search products in catalog", required=True
        ),
        AgentCapability(
            name="get_variant_price", description="Check variant price", required=False
        ),
        AgentCapability(
            name="check_stock", description="Check inventory availability", required=False
        ),
        AgentCapability(
            name="search_knowledge", description="Search store knowledge base", required=False
        ),
        AgentCapability(
            name="resolve_product_media",
            description="Retrieve product gallery photos",
            required=False,
        ),
        AgentCapability(
            name="find_product_by_image", description="Match product from image", required=False
        ),
    ],
    system_prompt_template=CUSTOMER_SYSTEM_PROMPT,
    default_model="fast",
    enforce_grounding=True,
    default_tools=CUSTOMER_TOOLS,
    allowed_tools=CUSTOMER_TOOLS,
    task_types=[
        "customer_inquiry",
        "product_search",
        "vision_match",
        "voice_turn",
    ],
    guardrail_profile="customer",
    provisioning_policy={
        "is_canonical": True,
        "auto_provision": True,
        "singleton_per_tenant": True,
    },
)

AgentRegistry.register(_DEFINITION)
