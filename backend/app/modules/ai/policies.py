"""The store's basic policies: what the customer agent answers from, written by the merchant.

A policy is an ordinary ``knowledge_items`` row, so the customer agent reads it through
``get_store_info`` with no change: ``source_type="policy"`` and a fixed ``source_ref`` key
identify it, which lets this screen find and edit it instead of piling up duplicates.

The four keys are fixed on purpose. These are the questions every customer asks, and the
agent has nothing to answer them with until the store writes them. The title is fixed too
(one source of truth for what the agent sees); the merchant only writes the text.
Nothing here invents a policy: an unwritten one stays unpublished, and the agent says so.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.ai.knowledge import embed_text
from app.modules.ai.models import KnowledgeItem

POLICY_SOURCE_TYPE = "policy"

# key -> title the agent sees. Order is the order the screen shows them.
POLICY_TITLES: dict[str, str] = {
    "exchange": "سياسة الاستبدال",
    "return": "سياسة الاسترجاع",
    "shipping": "الشحن والتوصيل",
    "hours": "مواعيد العمل",
}

# `get_store_info` stops at a 6000-character budget shared by everything the store published.
# Four policies must fit inside it with room for the rest, so each one is capped.
MAX_POLICY_CHARS = 1500


def _check_key(key: str) -> None:
    if key not in POLICY_TITLES:
        raise ValidationError(f"unknown policy '{key}': one of {', '.join(POLICY_TITLES)}")


async def _find(session: AsyncSession, tenant_id: uuid.UUID, key: str) -> KnowledgeItem | None:
    return (
        await session.execute(
            select(KnowledgeItem)
            .where(
                KnowledgeItem.tenant_id == tenant_id,
                KnowledgeItem.source_type == POLICY_SOURCE_TYPE,
                KnowledgeItem.source_ref == key,
            )
            .order_by(KnowledgeItem.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_policies(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    """All four policies, in screen order, whether or not the store has written them."""
    rows = (
        (
            await session.execute(
                select(KnowledgeItem)
                .where(
                    KnowledgeItem.tenant_id == tenant_id,
                    KnowledgeItem.source_type == POLICY_SOURCE_TYPE,
                )
                .order_by(KnowledgeItem.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    by_key: dict[str, KnowledgeItem] = {}
    for row in rows:
        by_key.setdefault(row.source_ref or "", row)  # the oldest wins, as in _find
    return [
        {
            "key": key,
            "title": title,
            "content": by_key[key].content if key in by_key else "",
            "published": key in by_key,
            "updated_at": (
                by_key[key].updated_at.isoformat()
                if key in by_key and by_key[key].updated_at
                else None
            ),
        }
        for key, title in POLICY_TITLES.items()
    ]


async def save_policy(session: AsyncSession, tenant_id: uuid.UUID, key: str, content: str) -> dict:
    """Create, replace or (blank text) remove one policy. Idempotent: saving twice is one row."""
    _check_key(key)
    text_ = (content or "").strip()
    if len(text_) > MAX_POLICY_CHARS:
        raise ValidationError(
            f"the policy is {len(text_)} characters; the limit is {MAX_POLICY_CHARS}"
        )
    item = await _find(session, tenant_id, key)

    if not text_:
        # Blank means "this store has no written policy": the row goes, so the agent says it
        # is unpublished. An empty row left behind would read as a policy with nothing in it.
        if item is not None:
            await session.delete(item)
            await session.flush()
        return {"key": key, "title": POLICY_TITLES[key], "content": "", "published": False}

    vector = await embed_text(session, tenant_id, text_)
    if item is None:
        item = KnowledgeItem(
            tenant_id=tenant_id,
            title=POLICY_TITLES[key],
            source_type=POLICY_SOURCE_TYPE,
            source_ref=key,
            content=text_,
            visibility="customer_facing",
            status="pending",
        )
        session.add(item)
    else:
        item.content = text_
        item.title = POLICY_TITLES[key]
        item.visibility = "customer_facing"
    # A changed text must never keep the old vector: semantic search would answer from words
    # the merchant already replaced. No embedding model => unindexed, still read by get_store_info.
    item.embedding = vector
    item.status = "indexed" if vector is not None else "pending"
    await session.flush()
    return {"key": key, "title": item.title, "content": item.content, "published": True}
