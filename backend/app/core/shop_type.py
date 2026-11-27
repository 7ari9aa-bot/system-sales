"""Choosing what kind of shop this is, and planting the branches a clothing shop starts with.

The vertical itself is only a setting. What this module adds is the one-time convenience of a
starting category tree, so a new clothing shop does not open an empty system. The tree is data (a
dict below), so another vertical's starting tree is another entry, not another code path.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import current_scope
from app.modules.catalog.models import Category
from app.modules.catalog.service import CatalogService
from app.modules.errors import ValidationError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.settings.service import SettingsService

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

# Map each vertical to its broad business segment (business.type).
# The segment decides which segment-specific settings the shop sees; the
# vertical decides which capabilities are on. They are two axes: a pharmacy
# is "retail" segment with "pharmacy" vertical.
VERTICAL_TO_SEGMENT: dict[str, str] = {
    "general": "retail",
    "apparel": "retail",
    "pharmacy": "retail",
    "restaurant": "fnb",
}


def _settings(session: AsyncSession, tenant_id: UUID) -> SettingsService:
    return SettingsService(session, tenant_id)


async def _has_categories(session: AsyncSession, tenant_id: UUID) -> bool:
    """Categories that belong to the scope this request is working in.

    The count used to be tenant-wide, so one business's catalog silenced the
    seeding for every other business in the same account: choosing apparel on a
    fresh workspace found the first workspace's categories, planted nothing, and
    the new workspace opened with an empty tree. A scoped request now asks about
    its own workspace; an unscoped one (worker, job, script) keeps the
    tenant-wide answer, because there is no workspace to be wrong about.
    """
    workspace_id, _location_id = current_scope()
    stmt = select(func.count()).select_from(Category).where(Category.tenant_id == tenant_id)
    if workspace_id is not None:
        stmt = stmt.where(Category.workspace_id == workspace_id)
    count = (await session.execute(stmt)).scalar_one()
    return count > 0


async def choose_vertical(
    session: AsyncSession, tenant_id: UUID, vertical: str, *, user_id: UUID | None
) -> dict[str, Any]:
    """Set the shop's vertical; plant its starting branches if the shop has none yet.

    Planting only happens into a shop with no categories at all, so choosing (or re-choosing)
    never touches what the owner has already built. The setting and the tree are written in one
    savepoint: either both land or neither does.
    """

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
        # Derive the broad business segment from the vertical so segment-
        # specific settings show or hide without a second manual step.
        segment = VERTICAL_TO_SEGMENT.get(vertical, "retail")
        await _settings(session, tenant_id).set("business.type", segment, user_id=user_id)
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
    return {"vertical": vertical, "business_type": segment, "categories_created": created}


async def current_vertical(session: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    """The vertical and business segment the shop runs now, and the vertical choices."""
    resolved_v = await _settings(session, tenant_id).resolve("business.vertical")
    resolved_t = await _settings(session, tenant_id).resolve("business.type")
    return {
        "current": resolved_v.value,
        "business_type": resolved_t.value,
        "choices": list(CHOOSABLE_VERTICALS),
    }


# ── The routes ─────────────────────────────────────────────────────────────────────────────────

router = APIRouter()
ShopTypeWriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


@router.get("/shop-type")
async def get_shop_type(ctx: TenantCtxDep):
    """The kinds of shop the owner can say they run, and the one they run now."""
    return await current_vertical(ctx.session, ctx.tenant_id)


@router.post("/shop-type/{vertical}")
async def choose_shop_type(vertical: str, ctx: ShopTypeWriteCtx):
    """Say what kind of shop this is. A clothing shop with no categories gets a starting tree."""
    return await choose_vertical(ctx.session, ctx.tenant_id, vertical, user_id=ctx.user.id)
