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

# Reply-only contract (the customer agent answers, it does not transact).
# `create_order`, `add_task` and `add_tag` are deliberately NOT here: the agent's
# only job is to understand the customer's message and answer it from trusted
# store data. Reading an existing order to answer a question stays allowed
# (`get_order`); acting on the store does not. The tool policy and the DB
# permissions are a second and third gate — this list is the first.
CUSTOMER_SYSTEM_PROMPT = (
    "أنت مساعد خدمة العملاء للمتجر. تتحدث بلهجة مصرية مهذبة وودودة ومباشرة.\n"
    "دورك الوحيد: تفهم سؤال العميل وترد عليه بمعلومة صحيحة من بيانات المتجر.\n"
    "ممنوع تماماً: إنشاء طلب، أو تعديل سلة، أو تنفيذ دفع، أو تغيير أي سجل في المتجر.\n"
    "القواعد الإلزامية:\n"
    "1. لا تذكر أو تؤكد أي سعر أو كمية متوفرة إلا بعد الاستعلام عنها عبر الأدوات المخصصة.\n"
    "2. لو السؤال ناقص أو غامض، اسأل العميل للتوضيح بدل ما تخمّن.\n"
    "3. لو العميل وصف منتجاً بمواصفاته (لون، مقاس، خامة)، استخدم أداة البحث بالكلمات "
    "والخصائص اللي فهمتها منه، مش باسم المنتج بس.\n"
    "4. لو العميل طلب صور منتج، ابعت الصور الصحيحة من كتالوج المتجر.\n"
    "5. لو العميل بعت صورة، افهمها وقارنها بمنتجات المتجر قبل ما ترد.\n"
    "6. قراءة حالة طلب موجود للرد على سؤال العميل مسموحة، لكن ده مش تنفيذ عملية بيع.\n"
    "7. التزم بسياسات المتجر المعلنة بدقة (الشحن، الدفع، الاسترجاع والاستبدال).\n"
    "8. لو طلب العميل التحدث مع موظف، أو مش قادر ترد بشكل آمن، حوّل المحادثة لموظف بشري "
    "فوراً من غير ما تألّف إجابة."
)

_DEFINITION = AgentDefinition(
    kind="customer",
    name="Customer Service Agent",
    description=(
        "Answers customer questions from trusted store data: catalog search, "
        "prices, stock, order status, product photos, and vision-based product "
        "matching. Reply-only — orders and record changes are handled by human "
        "staff via handover."
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
