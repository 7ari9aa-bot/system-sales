"""The tool specs shown to the model, and their registration.

Split out of the former single-file ``customer/tools.py``; the text is unchanged.
"""

from __future__ import annotations

from app.modules.ai.agents.customer.tools.catalog import (
    FindProductByImageArgs,
    GetProductDetailsArgs,
    GetProductPhotosArgs,
    SearchCatalogArgs,
    _find_product_by_image,
    _get_product_details,
    _get_product_photos,
    _search_catalog,
)
from app.modules.ai.agents.customer.tools.orders import GetMyOrdersArgs, _get_my_orders
from app.modules.ai.agents.customer.tools.store import (
    GetStoreInfoArgs,
    SearchKnowledgeArgs,
    _get_store_info,
    _search_knowledge,
)
from app.modules.ai.agents.customer.tools.support import (
    FindSupportPlaybookArgs,
    HandoverToHumanArgs,
    _find_support_playbook,
    _handover_to_human,
)
from app.modules.ai.tools import ToolSpec, register_tool

CUSTOMER_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_catalog",
        description=(
            "Search the store catalog. Use it when the customer mentions a "
            "product, a type, or specs (color, material, size) — pass their "
            "words as `query` and the specs you understood as `attributes` "
            "(product properties) and `option_values` (variant options like "
            "size). Words match with OR: one matching word is enough, and "
            "`total_matches` tells you how much is out there — many matches "
            "means show the best ones, zero means say nothing matched and "
            "retry once with a single word or a different spelling (تيشرت / "
            "تيشيرت) before telling the customer it is not found. Returns "
            "each variant with product_id, exact price and an availability "
            "status (متوفر / قليل / خلص / هيتجدد) plus the restock phrase "
            "when the item is out of stock. Do NOT use it for anything that "
            "is not a product the store sells."
        ),
        args_schema=SearchCatalogArgs,
        handler=_search_catalog,
        tags=["catalog"],
    ),
    ToolSpec(
        name="get_product_details",
        description=(
            "Full details for ONE product by id: attributes (material, "
            "properties) and every variant with price and availability. Use "
            "it when the customer asks what a product is made of, how it is "
            "cut, or which sizes/colors it has — usually after search_catalog "
            "found it."
        ),
        args_schema=GetProductDetailsArgs,
        handler=_get_product_details,
        tags=["catalog"],
    ),
    ToolSpec(
        name="get_product_photos",
        description=(
            "List one product's gallery image ids (primary image or all). "
            "Returns ids only — the server attaches the actual images to the "
            "reply. Use it when the customer wants to SEE the product."
        ),
        args_schema=GetProductPhotosArgs,
        handler=_get_product_photos,
        tags=["catalog"],
    ),
    ToolSpec(
        name="find_product_by_image",
        description=(
            "Identify a product from the customer's latest photo. Pass the "
            "kind you believe the photo is; the server attaches the photo "
            "itself. Non-product photos are refused with a handover reason."
        ),
        args_schema=FindProductByImageArgs,
        handler=_find_product_by_image,
        tags=["catalog", "vision"],
    ),
    ToolSpec(
        name="get_store_info",
        description=(
            "The store's own published facts: working hours, branches, "
            "shipping, payment, returns, and how to order. Use it for any "
            "question about the store itself or its policies. Pass the "
            "customer's question as `question` and the most relevant items "
            "come first; leave it out for the full list. Returns the store's "
            "knowledge items as title + content + updated_at — quote them, "
            "never invent a policy. `truncated` true means more items exist "
            "than were returned, so retry with `question` before saying the "
            "store has no answer. `ranking` unavailable means the relevance "
            "search is down; the items are still the store's real ones."
        ),
        args_schema=GetStoreInfoArgs,
        handler=_get_store_info,
        tags=["store"],
    ),
    # RETIRED from the customer agent (see CUSTOMER_TOOLS): get_store_info takes
    # an optional `question` and ranks by relevance, so the model no longer
    # picks between two tools over one table. It stays REGISTERED, and not
    # authorized for any agent kind, so historical tool_calls rows still
    # resolve and reconciliation quarantines tenant rows that still carry it.
    ToolSpec(
        name="search_knowledge",
        description=(
            "Retired: use get_store_info with `question`. Semantic search over "
            "the store's knowledge base."
        ),
        args_schema=SearchKnowledgeArgs,
        handler=_search_knowledge,
        tags=["knowledge"],
    ),
    ToolSpec(
        name="get_my_orders",
        description=(
            "Read ONE invoice the customer quotes by its number (the number "
            "printed on their receipt): status, date, items, totals, and "
            "whether goods were returned. Works on any channel with the number "
            "alone. `number` is required: ask the customer for it, never guess "
            "one and never list invoices. An empty result means that number "
            "does not exist, so ask them to re-check the receipt. Read-only: "
            "you cannot change, return or exchange anything. If the customer "
            "wants to return, exchange or cancel, answer from the invoice and "
            "the store policy yourself."
        ),
        args_schema=GetMyOrdersArgs,
        handler=_get_my_orders,
        tags=["orders"],
    ),
    ToolSpec(
        name="find_support_playbook",
        description=(
            "Find the store's written solution for a recurring customer "
            "problem (a late order, a wrong size, a payment that did not go "
            "through, how to track a shipment). Pass the problem in the "
            "customer's own words as `problem`. Each result has ordered "
            "`steps` and an `escalate_when` condition. Explain the steps in "
            "your own natural words, one or two at a time, and check how it "
            "went; never paste them as a list. If `escalate_when` is true for "
            "this customer, do not improvise a solution: call handover_to_human. "
            "If `matched` is 0, first try the rest of your tools (store info, "
            "catalog, the customer's invoice); hand over only if that still "
            "leaves a real problem unsolved."
        ),
        args_schema=FindSupportPlaybookArgs,
        handler=_find_support_playbook,
        tags=["support"],
    ),
    ToolSpec(
        name="handover_to_human",
        description=(
            "Escalate this conversation to a human staff member. This is the "
            "LAST resort, not the default: answer questions about products, "
            "sizes, colours, prices, stock, store policy and the customer's own "
            "invoice yourself with your tools, and never hand over a plain "
            "question or a customer who is just browsing or wants to buy. Use "
            "it only when (1) there is a real problem (complaint) and you "
            "tried the store's written solutions and your tools and could not "
            "solve it (complex_problem), (2) the information needed to solve "
            "that problem does not exist anywhere in the store's data after "
            "you searched it (missing_data), or (3) the customer explicitly "
            "asks for a person (customer_request). Pass `reason` and a "
            "`summary` saying what you tried and what stopped you. After "
            "calling it, write one short natural reply telling the customer a "
            "team member will continue with them."
        ),
        args_schema=HandoverToHumanArgs,
        handler=_handover_to_human,
        tags=["escalation"],
        risk_level="MEDIUM",
    ),
]


def register_customer_tools() -> list[ToolSpec]:
    """Register all customer agent tools into the central platform registry."""
    for spec in CUSTOMER_TOOL_SPECS:
        register_tool(spec)
    return CUSTOMER_TOOL_SPECS
