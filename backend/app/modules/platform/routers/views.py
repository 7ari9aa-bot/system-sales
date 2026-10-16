"""Platform saved views (§95) — cross-cutting list layout store."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.platform import schemas
from app.modules.platform.models import SavedView
from app.modules.platform.routers._deps import (
    PageLimit,
    PageOffset,
    TenantContext,
    TenantCtxDep,
)

router = APIRouter(prefix="/platform", tags=["platform"])

SAVED_VIEW_VISIBILITIES = frozenset({"private", "team", "workspace"})
SAVED_VIEW_NAME_MAX = 255  # matches saved_views.name String(255)
SAVED_VIEW_ENTITY_MAX = 63  # matches saved_views.entity String(63)


class SavedViewCreate(BaseModel):
    """Body for ``POST /platform/saved-views``."""

    name: str = Field(min_length=1, max_length=SAVED_VIEW_NAME_MAX)
    entity: str = Field(min_length=1, max_length=SAVED_VIEW_ENTITY_MAX)
    # filters / sort / columns / grouping / density — stored verbatim.
    definition: dict = Field(default_factory=dict)
    visibility: str = "private"


class SavedViewUpdate(BaseModel):
    """Body for ``PATCH /platform/saved-views/{id}`` — every field optional."""

    name: str | None = Field(default=None, min_length=1, max_length=SAVED_VIEW_NAME_MAX)
    definition: dict | None = None
    visibility: str | None = None


def can_read_saved_view(view: SavedView, *, user_id: uuid.UUID) -> bool:
    """team/workspace views are tenant-visible; a private view is owner-only."""
    if view.visibility in ("team", "workspace"):
        return True
    return view.visibility == "private" and view.owner_user_id == user_id


def can_modify_saved_view(
    view: SavedView, *, user_id: uuid.UUID, permission_codes: set[str]
) -> bool:
    """Who may PATCH/DELETE a saved view.

    private   -> the owner only. It is the caller's own scratch layout, so
                 nobody else may rewrite it — not even an admin with
                 settings:write.
    team      -> the owner, or anyone holding settings:write. A team view is
                 shared, but curating what the team sees is an administrative
                 act rather than something every member should do silently.
    workspace -> settings:write only, even for the owner. This is the widest
                 blast radius: the view is visible to the whole workspace, so a
                 silent rewrite by any member would change what everyone sees.
                 Requiring a permission is what stops a shared view from being
                 a footgun; ownership alone is not enough.

    An unknown visibility is denied rather than guessed.

    Note this rule IS the authorization for these routes: a private view is a
    personal preference, not a settings change, so a blanket settings:write
    gate would (wrongly) stop an ordinary user from editing their own view.
    """
    if view.visibility == "private":
        return view.owner_user_id == user_id
    if view.visibility == "team":
        return view.owner_user_id == user_id or "settings:write" in permission_codes
    if view.visibility == "workspace":
        return "settings:write" in permission_codes
    return False


def _view_out(view: SavedView) -> dict:
    return {
        "id": str(view.id),
        "name": view.name,
        "entity": view.entity,
        "definition": view.definition or {},
        "visibility": view.visibility,
        "owner_user_id": str(view.owner_user_id) if view.owner_user_id else None,
        "created_at": view.created_at.isoformat() if view.created_at else None,
        "updated_at": view.updated_at.isoformat() if view.updated_at else None,
    }


async def _load_view(ctx: TenantContext, view_id: uuid.UUID) -> SavedView:
    """Fetch a view the caller may see; 404 when it exists but is not visible.

    A private view belonging to somebody else answers 404, not 403 — its very
    existence is private information.
    """
    view = (
        await ctx.session.execute(
            select(SavedView).where(SavedView.tenant_id == ctx.tenant_id, SavedView.id == view_id)
        )
    ).scalar_one_or_none()
    if view is None or not can_read_saved_view(view, user_id=ctx.user.id):
        raise NotFoundError("saved view not found")
    return view


@router.get("/saved-views", response_model=schemas.SavedViewListOut)
async def list_saved_views(
    ctx: TenantCtxDep,
    entity: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """The caller's own private views plus every team/workspace view.

    Another user's private view is filtered in the query, never returned and
    left for the client to hide.

    Paged, and ordered by ``(name, id)`` rather than ``name`` alone.
    ``saved_views.name`` carries no unique constraint — a tenant can hold two
    views called "Default", one for customers and one for orders, and PostgreSQL
    owes nothing for their relative order. On a single unbounded read that is
    invisible; the moment a page exists it is not: the tied pair can swap places
    between two reads, so one of them crosses the page boundary and the caller
    either sees it twice or never. ``id`` (the primary key) is the tie-break that
    makes ``ORDER BY`` a total order, exactly as the webhook and security-event
    lists already do.

    ``total`` is the size of the WHOLE filtered list, so a client that receives
    ``len(items) < total`` knows it is looking at one page rather than at
    everything it has.
    """
    conditions = [
        SavedView.tenant_id == ctx.tenant_id,
        or_(
            and_(
                SavedView.visibility == "private",
                SavedView.owner_user_id == ctx.user.id,
            ),
            SavedView.visibility.in_(("team", "workspace")),
        ),
    ]
    if entity:
        conditions.append(SavedView.entity == entity)
    total = (
        await ctx.session.execute(select(func.count(SavedView.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(SavedView)
                .where(*conditions)
                .order_by(SavedView.name, SavedView.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_view_out(view) for view in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.post("/saved-views", response_model=schemas.SavedViewOut, status_code=201)
async def create_saved_view(ctx: TenantCtxDep, body: SavedViewCreate):
    """Create a saved view owned by the caller."""
    if body.visibility not in SAVED_VIEW_VISIBILITIES:
        raise ValidationError(
            f"visibility must be one of {sorted(SAVED_VIEW_VISIBILITIES)}",
            details={"visibility": body.visibility},
        )
    # A workspace-visible view is visible to the whole tenant, so creating one
    # is a shared-resource write rather than a personal preference.
    if body.visibility == "workspace" and "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("creating a workspace view requires settings:write")
    view = SavedView(
        tenant_id=ctx.tenant_id,
        name=body.name,
        entity=body.entity,
        definition=body.definition,
        visibility=body.visibility,
        owner_user_id=ctx.user.id,
    )
    ctx.session.add(view)
    await ctx.session.flush()
    return _view_out(view)


@router.get("/saved-views/{view_id}", response_model=schemas.SavedViewOut)
async def get_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID):
    """One saved view, if the caller may see it."""
    return _view_out(await _load_view(ctx, view_id))


@router.patch("/saved-views/{view_id}", response_model=schemas.SavedViewOut)
async def update_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID, body: SavedViewUpdate):
    """Rename, re-scope or re-define a view the caller may modify."""
    view = await _load_view(ctx, view_id)
    if not can_modify_saved_view(view, user_id=ctx.user.id, permission_codes=ctx.permission_codes):
        raise PermissionDeniedError("you may not modify this saved view")
    if body.visibility is not None and body.visibility not in SAVED_VIEW_VISIBILITIES:
        raise ValidationError(
            f"visibility must be one of {sorted(SAVED_VIEW_VISIBILITIES)}",
            details={"visibility": body.visibility},
        )
    if body.name is not None:
        view.name = body.name
    if body.definition is not None:
        view.definition = body.definition
    if body.visibility is not None:
        view.visibility = body.visibility
    await ctx.session.flush()
    return _view_out(view)


@router.delete("/saved-views/{view_id}", response_model=schemas.SavedViewDeletedOut)
async def delete_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID):
    """Delete a view the caller may modify."""
    view = await _load_view(ctx, view_id)
    if not can_modify_saved_view(view, user_id=ctx.user.id, permission_codes=ctx.permission_codes):
        raise PermissionDeniedError("you may not modify this saved view")
    await ctx.session.delete(view)
    await ctx.session.flush()
    return {"id": str(view_id), "deleted": True}
