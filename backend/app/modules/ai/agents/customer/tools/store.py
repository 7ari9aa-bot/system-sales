"""Store information tools: get_store_info and search_knowledge.

Split out of the former single-file ``customer/tools.py``; the code is unchanged.
"""

from __future__ import annotations

import uuid

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ValidationError
from app.modules.ai.agents.customer.tools._shared import _StrictArgs


class GetStoreInfoArgs(_StrictArgs):
    """The store's published info: one deterministic pull, optionally ranked.

    `question` only changes the ORDER: the same customer-facing items come back
    either way, most relevant first, so a long knowledge base cuts the least
    relevant items at the budget instead of the newest ones.
    """

    question: str | None = Field(default=None, min_length=1, max_length=1000)


async def _get_store_info(
    session: AsyncSession, tenant_id: uuid.UUID, *, question: str | None = None
) -> dict:
    """The store's own published facts: hours, branches, shipping, payment,
    returns, how to order.

    Backed by the tenant's customer-facing knowledge items read directly —
    no embedding call, fully deterministic. The merchant owns the content;
    behavior lives in prompts, facts live HERE.
    """
    from app.modules.ai.models import KnowledgeItem

    _LIMIT = 30
    ranking: str | None = None
    ranked_ids: list[uuid.UUID] = []
    if question:
        # Relevance ordering is a bonus on top of a pull that never needs the
        # embedding model. When retrieval is down the items still come back
        # (hours and returns must not depend on a vendor call), but the
        # failure is SAID, not swallowed: a broken RAG setup has to stay
        # visible rather than read as "nothing matched".
        from app.modules.ai import knowledge

        try:
            hits = await knowledge.search_knowledge(
                session, tenant_id, question, limit=_LIMIT, visibility="customer_facing"
            )
            ranked_ids = [item.id for item, _distance in hits]
            ranking = "by_relevance"
        except ValidationError:
            ranking = "unavailable"

    columns = (
        KnowledgeItem.id,
        KnowledgeItem.title,
        KnowledgeItem.content,
        KnowledgeItem.updated_at,
    )
    visible = (
        KnowledgeItem.tenant_id == tenant_id,
        KnowledgeItem.visibility == "customer_facing",
    )
    # Ranking must happen BEFORE the cut: fetching the first N by age and then
    # sorting them would never surface a relevant item that sits past N.
    ranked_rows: list = []
    if ranked_ids:
        fetched = (
            await session.execute(
                select(*columns).where(*visible, KnowledgeItem.id.in_(ranked_ids))
            )
        ).all()
        by_id = {r[0]: r for r in fetched}
        ranked_rows = [by_id[i] for i in ranked_ids if i in by_id]
    remaining = (
        await session.execute(
            select(*columns)
            .where(*visible, KnowledgeItem.id.notin_([r[0] for r in ranked_rows]))
            .order_by(KnowledgeItem.created_at.asc())
            # Enough to fill what the ranked items left of the cap, plus one,
            # so "there was more" is known rather than guessed.
            .limit(max(_LIMIT - len(ranked_rows), 0) + 1)
        )
    ).all()
    rows = [*ranked_rows, *remaining]
    # Token ceiling: content is merchant-authored Text with no upper bound,
    # so the pull stops at the budget instead of flooding the model's context
    # (a tool response cap, per the tool-design guidance).
    _BUDGET = 6000
    items: list[dict] = []
    spent = 0
    truncated = len(rows) > _LIMIT
    for _item_id, title, content, updated_at in rows[:_LIMIT]:
        cost = len(title) + len(content)
        if spent + cost > _BUDGET and items:
            truncated = True
            break
        items.append(
            {
                "title": title,
                "content": content,
                # ISO on purpose: the fact ledger skips `*_at` keys, so the
                # model can judge how old an answer is without the timestamp
                # becoming a numeral it may quote.
                "updated_at": updated_at.isoformat() if updated_at else None,
            }
        )
        spent += cost
    # `truncated` tells the model the list is NOT the whole store: silence
    # about a missing policy must not read as "the store has none".
    result: dict = {"items": items, "truncated": truncated}
    if not items:
        # An empty list reads as "nothing to say", and a model fills that gap with
        # a policy of its own or with a handover. Say plainly what is true: the
        # store has not published this information. It is not a customer
        # problem, so it is answered, not handed over.
        result["note"] = (
            "المتجر لسه منشرش أي معلومات هنا (سياسات أو مواعيد أو شحن). متخترعش "
            "سياسة ومتوعدش بحاجة. قول للعميل بصراحة إن المعلومة دي مش متاحة "
            "عندك دلوقتي، وكمّل معاه فيما تقدر عليه، ومتحوّلوش لمجرد ده."
        )
    if ranking is not None:
        result["ranking"] = ranking
    return result


class SearchKnowledgeArgs(_StrictArgs):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=3, ge=1, le=10)


async def _search_knowledge(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    query: str,
    limit: int = 3,
) -> dict:
    from app.modules.ai import knowledge

    try:
        hits = await knowledge.search_knowledge(
            session, tenant_id, query, limit=limit, visibility="customer_facing"
        )
    except ValidationError as exc:
        raise DomainError(f"knowledge search unavailable: {exc}") from exc
    return {
        "results": [
            {
                "title": item.title,
                "content": item.content,
                "source_type": item.source_type,
            }
            for item, _distance in hits
        ]
    }
