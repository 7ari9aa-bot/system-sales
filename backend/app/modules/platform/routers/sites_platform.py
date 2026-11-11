"""Owner console: the "Websites" section that manages the Fihrist Sites platform.

Fihrist Sites is a separate product (its own database). This router is the owner's
window onto it, behind the same platform-admin gate as the rest of ``/owner``.

What it does: list purchases, sites, designs, limits, legal pages, Fihrist links and
per-site activity; change a design's price/visibility, a merchant limit, a legal page,
a link's sync switch, and a site's active/suspended state.

What it deliberately does NOT do: confirm a payment, delete a site, delete a merchant,
or show any customer's name/phone/address. Those stay in the platform's own console,
which asks for a payment reference / a typed site name first. Copying the action
without its guard would be worse than not copying it.

With the two settings empty (the default) every route answers 503 "not configured".
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.modules.platform.routers._deps import TenantCtxDep, _require_platform_admin
from app.modules.platform.services import sites_platform as sp
from app.modules.platform.services.audit import AuditService

router = APIRouter(prefix="/owner/sites-platform", tags=["owner"])

_LEGAL_SLUGS = frozenset(
    {"privacy", "terms", "payment", "refunds", "acceptable-use", "service-terms", "cookies"}
)
_SITE_STATUS = frozenset({"active", "suspended"})
_LIMIT_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# At most this many sites get live counts, and only a few requests run at once.
_COUNTED_SITES = 50
_CONCURRENCY = 3  # ten reads per site now, so fewer sites at once
_SUM_ROWS = 500
_VIEW_DAYS = 30
_CANCELLED = "ملغي"
_OPEN = ("جديد", "قيد التجهيز")  # an order the merchant still has to deal with


def _money_sum(rows: list[dict[str, Any]], field: str) -> str:
    """Total as an exact decimal string. Money never goes through float."""
    total = Decimal(0)
    for r in rows:
        try:
            total += Decimal(str(r.get(field) or 0))
        except ArithmeticError:
            continue
    return format(total, "f")


def _guard(ctx: TenantCtxDep) -> None:
    _require_platform_admin(ctx)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, sp.SitesPlatformNotConfigured):
        return HTTPException(status_code=503, detail="Fihrist Sites platform is not configured")
    if isinstance(exc, sp.SitesPlatformError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    raise exc


class StatusOut(BaseModel):
    configured: bool


class ItemsOut(BaseModel):
    items: list[dict[str, Any]]


class DoneOut(BaseModel):
    ok: bool = True
    changed: int = 0


class DesignIn(BaseModel):
    is_listed: bool | None = None
    price_egp: int | None = Field(default=None, ge=0, le=10_000_000)


class LimitIn(BaseModel):
    # Named `limit`, not `value`: `value` is a money field name in the published-contract guard
    # (test_marketing_analytics_contracts), and a quota is a count, not an amount of money.
    limit: int = Field(ge=0, le=10**12)


class LegalSection(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=6000)


class LegalEditIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=400)
    sections: list[LegalSection] = Field(min_length=1, max_length=40)


class PublishIn(BaseModel):
    publish: bool


class SyncIn(BaseModel):
    sync_enabled: bool


class SiteStatusIn(BaseModel):
    status: str


def _clean(text: str) -> str:
    return text.replace("\x00", "").strip()


async def _audit(ctx: TenantCtxDep, action: str, target: str, **after: Any) -> None:
    await AuditService.write(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        f"sites_platform.{action}",
        "sites_platform",
        target,
        after=after or None,
    )
    await ctx.session.commit()


@router.get("/status", response_model=StatusOut)
async def sites_platform_status(ctx: TenantCtxDep) -> StatusOut:
    """Lets the screen show "not configured" instead of a wall of errors."""
    _guard(ctx)
    return StatusOut(configured=sp.is_configured())


@router.get("/purchases", response_model=ItemsOut)
async def list_purchases(
    ctx: TenantCtxDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> ItemsOut:
    _guard(ctx)
    try:
        rows = await sp.select("purchase_orders", order="-created_at", limit=limit)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    return ItemsOut(items=rows)


@router.get("/designs", response_model=ItemsOut)
async def list_designs(ctx: TenantCtxDep) -> ItemsOut:
    _guard(ctx)
    try:
        rows = await sp.select("designs", order="sort_order", limit=100)
        sites = await sp.select("sites", limit=500)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    used: dict[str, int] = {}
    for s in sites:
        used[s["design"]] = used.get(s["design"], 0) + 1
    return ItemsOut(items=[{**d, "sites": used.get(d["key"], 0)} for d in rows])


@router.patch("/designs/{key}", response_model=DoneOut)
async def edit_design(ctx: TenantCtxDep, key: str, body: DesignIn) -> DoneOut:
    _guard(ctx)
    safe = sp.key_or_none(key)
    values = body.model_dump(exclude_none=True)
    if safe is None or not values:
        raise HTTPException(status_code=400, detail="invalid design or nothing to change")
    try:
        changed = await sp.update("designs", {"key": safe}, values)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    if changed == 0:
        raise HTTPException(status_code=404, detail="design not found")
    await _audit(ctx, "design.edit", safe, **values)
    return DoneOut(changed=changed)


@router.get("/limits", response_model=ItemsOut)
async def list_limits(ctx: TenantCtxDep) -> ItemsOut:
    _guard(ctx)
    try:
        rows = await sp.select("platform_limits", order="key", limit=100)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    return ItemsOut(items=rows)


@router.put("/limits/{key}", response_model=DoneOut)
async def set_limit(ctx: TenantCtxDep, key: str, body: LimitIn) -> DoneOut:
    _guard(ctx)
    if not _LIMIT_KEY.match(key):
        raise HTTPException(status_code=400, detail="invalid limit key")
    try:
        changed = await sp.update("platform_limits", {"key": key}, {"value": body.limit})
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    if changed == 0:
        raise HTTPException(status_code=404, detail="unknown limit")
    await _audit(ctx, "limit.set", key, value=body.limit)
    return DoneOut(changed=changed)


@router.get("/legal", response_model=ItemsOut)
async def list_legal(ctx: TenantCtxDep) -> ItemsOut:
    _guard(ctx)
    try:
        rows = await sp.select("platform_legal", order="sort_order", limit=20)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    return ItemsOut(items=rows)


@router.put("/legal/{slug}", response_model=DoneOut)
async def edit_legal(ctx: TenantCtxDep, slug: str, body: LegalEditIn) -> DoneOut:
    """An edit always returns the page to draft: new legal text is never public unseen."""
    _guard(ctx)
    if slug not in _LEGAL_SLUGS:
        raise HTTPException(status_code=404, detail="unknown legal page")
    sections = [{"title": _clean(s.title), "body": _clean(s.body)} for s in body.sections]
    title = _clean(body.title)
    if not title or any(not s["title"] or not s["body"] for s in sections):
        raise HTTPException(status_code=400, detail="title and every section need text")
    now = datetime.now(UTC).isoformat()
    try:
        changed = await sp.update(
            "platform_legal",
            {"slug": slug},
            {
                "title": title,
                "summary": _clean(body.summary),
                "sections": sections,
                "is_draft": True,
                "updated_at": now,
                "owner_edited_at": now,
            },
        )
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    if changed == 0:
        raise HTTPException(status_code=404, detail="unknown legal page")
    await _audit(ctx, "legal.edit", slug, sections=len(sections))
    return DoneOut(changed=changed)


@router.post("/legal/{slug}/publish", response_model=DoneOut)
async def publish_legal(ctx: TenantCtxDep, slug: str, body: PublishIn) -> DoneOut:
    _guard(ctx)
    if slug not in _LEGAL_SLUGS:
        raise HTTPException(status_code=404, detail="unknown legal page")
    now = datetime.now(UTC).isoformat()
    values: dict[str, Any] = (
        {"is_draft": False, "published_at": now, "updated_at": now}
        if body.publish
        else {"is_draft": True, "updated_at": now}
    )
    try:
        changed = await sp.update("platform_legal", {"slug": slug}, values)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    if changed == 0:
        raise HTTPException(status_code=404, detail="unknown legal page")
    await _audit(ctx, "legal.publish" if body.publish else "legal.unpublish", slug)
    return DoneOut(changed=changed)


@router.get("/fihrist-links", response_model=ItemsOut)
async def list_links(ctx: TenantCtxDep) -> ItemsOut:
    """Which sites are linked to a Fihrist account. The encrypted key is not in the allow-list."""
    _guard(ctx)
    try:
        links = await sp.select("fihrist_links", order="-linked_at", limit=200)
        ids = [str(row["site_id"]) for row in links]
        sites = await sp.select("sites", in_=("id", ids), limit=500) if ids else []
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    by_id = {s["id"]: s for s in sites}
    return ItemsOut(items=[{**row, "site": by_id.get(row["site_id"])} for row in links])


@router.patch("/fihrist-links/{site_id}", response_model=DoneOut)
async def set_link_sync(ctx: TenantCtxDep, site_id: str, body: SyncIn) -> DoneOut:
    _guard(ctx)
    safe = sp.uuid_or_none(site_id)
    if safe is None:
        raise HTTPException(status_code=400, detail="invalid site id")
    try:
        changed = await sp.update(
            "fihrist_links", {"site_id": safe}, {"sync_enabled": body.sync_enabled}
        )
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    if changed == 0:
        raise HTTPException(status_code=404, detail="this site is not linked")
    await _audit(ctx, "fihrist.sync", safe, sync_enabled=body.sync_enabled)
    return DoneOut(changed=changed)


@router.get("/sites", response_model=ItemsOut)
async def list_sites(ctx: TenantCtxDep) -> ItemsOut:
    """Per-site activity, numbers only. No customer name, phone or address passes through here.

    Customers and subscribers are deliberately NOT counted: those tables hold names, phones and
    emails, and the client never lists a table like that, even for a count.

    Orders, revenue and open orders leave out cancelled ones. Revenue and views are summed over at
    most ``_SUM_ROWS`` rows, and ``revenue_capped`` / ``views_capped`` say so when a site has more,
    so a big shop shows "at least" instead of a quietly wrong total.
    """
    _guard(ctx)
    since = (datetime.now(UTC) - timedelta(days=_VIEW_DAYS)).date().isoformat()
    try:
        sites = await sp.select("sites", order="-created_at", limit=_COUNTED_SITES)
        gate = asyncio.Semaphore(_CONCURRENCY)

        async def activity(site_id: str) -> dict[str, Any]:
            async with gate:
                (
                    n_products,
                    n_orders,
                    n_coupons,
                    n_msgs,
                    paid_rows,
                    open_new,
                    open_prep,
                    view_rows,
                ) = await asyncio.gather(
                    sp.select("products", eq={"site_id": site_id}, count_only=True),
                    sp.select(
                        "orders",
                        eq={"site_id": site_id},
                        neq={"status": _CANCELLED},
                        count_only=True,
                    ),
                    sp.select(
                        "coupons", eq={"site_id": site_id, "is_active": "true"}, count_only=True
                    ),
                    sp.select("contact_messages", eq={"site_id": site_id}, count_only=True),
                    sp.select(
                        "orders",
                        eq={"site_id": site_id},
                        neq={"status": _CANCELLED},
                        limit=_SUM_ROWS,
                    ),
                    sp.select(
                        "orders", eq={"site_id": site_id, "status": _OPEN[0]}, count_only=True
                    ),
                    sp.select(
                        "orders", eq={"site_id": site_id, "status": _OPEN[1]}, count_only=True
                    ),
                    sp.select(
                        "page_stats", eq={"site_id": site_id}, gte={"day": since}, limit=_SUM_ROWS
                    ),
                )
                return {
                    "products": n_products,
                    "orders": n_orders,
                    "open_orders": open_new + open_prep,
                    "coupons": n_coupons,
                    "messages": n_msgs,
                    "revenue": _money_sum(paid_rows, "total"),
                    "revenue_capped": len(paid_rows) >= _SUM_ROWS,
                    "views_30d": sum(int(r.get("views") or 0) for r in view_rows),
                    "views_capped": len(view_rows) >= _SUM_ROWS,
                }

        rows = await asyncio.gather(*(activity(s["id"]) for s in sites))
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    return ItemsOut(items=[{**s, **c} for s, c in zip(sites, rows, strict=True)])


@router.patch("/sites/{site_id}", response_model=DoneOut)
async def set_site_status(ctx: TenantCtxDep, site_id: str, body: SiteStatusIn) -> DoneOut:
    """Suspend or reactivate. Deleting is NOT offered here (needs the typed-name guard)."""
    _guard(ctx)
    safe = sp.uuid_or_none(site_id)
    if safe is None or body.status not in _SITE_STATUS:
        raise HTTPException(status_code=400, detail="invalid site or status")
    try:
        changed = await sp.update("sites", {"id": safe}, {"status": body.status})
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    if changed == 0:
        raise HTTPException(status_code=404, detail="site not found")
    await _audit(ctx, "site.status", safe, status=body.status)
    return DoneOut(changed=changed)


@router.get("/audit", response_model=ItemsOut)
async def platform_audit(
    ctx: TenantCtxDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> ItemsOut:
    """The platform's own owner log (what was done from ITS console)."""
    _guard(ctx)
    try:
        rows = await sp.select("owner_audit", order="-created_at", limit=limit)
    except (sp.SitesPlatformError, sp.SitesPlatformNotConfigured) as exc:
        raise _http(exc) from exc
    return ItemsOut(items=rows)
