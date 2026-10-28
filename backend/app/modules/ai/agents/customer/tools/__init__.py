"""Customer Agent tool implementations and specs.

The customer agent is LANGUAGE-ONLY: it answers from store data and hands over to a person
when it cannot solve a real problem. It never sells and never mutates records. Nine tools,
every one read-only except the escalation (the names below are the registered tool names, and
``CUSTOMER_TOOL_SPECS`` at the bottom of this file is the authoritative list):

- Catalog: search_catalog, get_product_details, get_product_photos
- Vision: find_product_by_image
- Store: get_store_info, search_knowledge
- Customer's own purchases: get_my_orders (looked up by invoice number)
- Support: find_support_playbook (the store's written solutions)
- Escalation: handover_to_human

Descriptions follow the platform guidance (Anthropic's tool-design notes,
OpenAI's function-calling guide): state what the tool does, when to use it,
when NOT to use it, and what it returns. The server binds customer and
conversation from its own context — the model never passes them.


This package replaced a single 1,270-line ``tools.py``. Every name that file exposed is
re-exported here, so ``from app.modules.ai.agents.customer.tools import X`` keeps working.
The tools live in ``catalog``, ``orders``, ``store`` and ``support``; ``_shared`` holds what they
all use and ``specs`` holds the text the model sees and the registration.
"""

# ruff: noqa: F401  (this module exists to re-export; the imports ARE the public surface)
from __future__ import annotations

from app.modules.ai.agents.customer.tools._shared import (
    _money,
    _parse_bound_id,
    _StrictArgs,
    sellable_product_statuses,
)
from app.modules.ai.agents.customer.tools.catalog import (
    _ARABIC_MONTHS,
    LOW_STOCK_THRESHOLD,
    FindProductByImageArgs,
    GetProductDetailsArgs,
    GetProductPhotosArgs,
    SearchCatalogArgs,
    _availability_map,
    _find_product_by_image,
    _get_product_details,
    _get_product_photos,
    _restock_label,
    _search_catalog,
    _selling_warehouse_ids,
    _unit_prices,
    media_payload_for_ids,
)
from app.modules.ai.agents.customer.tools.orders import (
    _NOT_FOUND_HINT,
    GetMyOrdersArgs,
    _get_my_orders,
)
from app.modules.ai.agents.customer.tools.specs import CUSTOMER_TOOL_SPECS, register_customer_tools
from app.modules.ai.agents.customer.tools.store import (
    GetStoreInfoArgs,
    SearchKnowledgeArgs,
    _get_store_info,
    _search_knowledge,
)
from app.modules.ai.agents.customer.tools.support import (
    _PLAYBOOK_GENERIC,
    _PLAYBOOK_STOPWORDS,
    FindSupportPlaybookArgs,
    HandoverToHumanArgs,
    _find_support_playbook,
    _fold_arabic,
    _fold_sql,
    _handover_to_human,
    _playbook_word_arms,
    _strip_clitic,
)

__all__ = [
    "CUSTOMER_TOOL_SPECS",
    "FindProductByImageArgs",
    "FindSupportPlaybookArgs",
    "GetMyOrdersArgs",
    "GetProductDetailsArgs",
    "GetProductPhotosArgs",
    "GetStoreInfoArgs",
    "HandoverToHumanArgs",
    "LOW_STOCK_THRESHOLD",
    "SearchCatalogArgs",
    "SearchKnowledgeArgs",
    "media_payload_for_ids",
    "register_customer_tools",
    "sellable_product_statuses",
]
