"""Choosing what kind of shop this is, and planting the branches a clothing shop starts with.

The vertical itself is only a setting. What this module adds is the one-time convenience of a
starting category tree, so a new clothing shop does not open an empty system. The tree is data (a
dict below), so another vertical's starting tree is another entry, not another code path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Category
from app.modules.errors import ValidationError

# Only the verticals that behave differently from a plain shop are offered. Pharmacy and
# restaurant exist in the capability table, but choosing them today would change nothing, so the
# owner is not offered a choice that does nothing.
CHOOSABLE_VERTICALS: tuple[str, ...] = ("general", "apparel")

# vertical -> {branch: [sub-branches]}. The owner edits all of it afterwards.
STARTER_TREES: dict[str, dict[str, tuple[str, ...]]] = {
    "apparel": {
        "رجالي": ("قمصان", "بناطيل", "جاكيتات", "ملابس داخلية", "أحذية"),
        "نسائي": ("فساتين", "بلوزات", "بناطيل", "عبايات", "ملابس داخلية", "أحذية"),
        "أطفال": ("أولاد", "بنات", "أحذية"),
        "مواليد": ("أطقم", "بودي"),
    },
}
APPAREL_STARTER_TREE = STARTER_TREES["apparel"]


def _settings(session: AsyncSession, tenant_id: UUID):
    # Lazy on purpose: a module-scope import would add a permanent catalog -> settings edge.
    from app.modules.settings.service import SettingsService

    return SettingsService(session, tenant_id)


async def _has_categories(session: AsyncSession, tenant_id: UUID) -> bool:
    count = (
        await session.execute(
            select(func.count()).select_from(Category).where(Category.tenant_id == tenant_id)
        )
    ).scalar_one()
    return count > 0


async def choose_vertical(
    session: AsyncSession, tenant_id: UUID, vertical: str, *, user_id: UUID | None
) -> dict[str, Any]:
    """Set the shop's vertical; plant its starting branches if the shop has none yet.

    Planting only happens into a shop with no categories at all, so choosing (or re-choosing)
    never touches what the owner has already built. The setting and the tree are written in one
    savepoint: either both land or neither does.
    """
    from app.modules.catalog.services import CatalogService

    if vertical not in CHOOSABLE_VERTICALS:
        raise ValidationError(f"vertical must be one of {sorted(CHOOSABLE_VERTICALS)}")

    created = 0
    async with session.begin_nested():
        # One chooser per shop at a time. Without this, two taps at once both see "no categories
        # yet" and plant two trees. It must not rely on the settings write below happening to lock
        # a row: that is a side effect, and a reordering would silently reopen the race.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"choose_vertical:{tenant_id}"},
        )
        await _settings(session, tenant_id).set("business.vertical", vertical, user_id=user_id)
        tree = STARTER_TREES.get(vertical)
        if tree and not await _has_categories(session, tenant_id):
            for branch, children in tree.items():
                parent = await CatalogService.create_category(session, tenant_id, name=branch)
                created += 1
                for child in children:
                    await CatalogService.create_category(
                        session, tenant_id, name=child, parent_id=parent.id
                    )
                    created += 1
    return {"vertical": vertical, "categories_created": created}


async def current_vertical(session: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    """The vertical the shop runs now and the ones it may choose."""
    resolved = await _settings(session, tenant_id).resolve("business.vertical")
    return {"current": resolved.value, "choices": list(CHOOSABLE_VERTICALS)}
