"""«My Website» API surfaces — the in-house website builder.

Three surfaces live here:

- ``router`` — mounted under ``/api/v1`` by app.main: the merchant surface
  (tenant-gated via ``TenantCtxDep``, same precedent as every dashboard
  module) and the platform-admin purchase queue (``require_platform_admin``).
- ``public_sites_router`` — mounted at ROOT by app.main: the unauthenticated
  public site renderer. ``GET /sites/{slug}`` serves a published site by path
  today; ``GET /`` serves by Host header once wildcard DNS is on
  (docs/SITES_SERVING.md), so the same handler covers both phases.

Routers parse and authorise, then call services — no rows are written here.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.identity.deps import DbSession, TenantContext, TenantCtxDep
from app.modules.identity.models import Tenant
from app.modules.website.services import (
    content_service,
    preview_service,
    public_service,
    purchase_service,
)
from app.modules.website.services.publishing_service import publish as publish_website
from app.modules.website.services.publishing_service import rollback as rollback_website
from app.modules.website.templates import catalog

router = APIRouter(tags=["website"])
public_sites_router = APIRouter(tags=["public-sites"])


def _require_console_admin(ctx: TenantContext) -> None:
    """The purchase queue is the deployment operator's plane: the same
    platform-admin gate the owner console applies, checked INSIDE the request
    so every route keeps get_tenant_ctx in its dependency chain (the
    resource-route audit requires membership + RLS binding on each handler)."""
    if not ctx.user.is_platform_admin:
        raise PermissionDeniedError("platform admin access required")


def _uuid(raw: str, *, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ValidationError(f"{what} is not a valid id") from exc


def _money(value) -> str:  # noqa: ANN001 - Decimal from Numeric columns
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Merchant surface
# ---------------------------------------------------------------------------


class PurchaseIn(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    site_name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    payment_reference: str | None = Field(default=None, max_length=200)


class PaymentReferenceIn(BaseModel):
    reference: str = Field(min_length=1, max_length=200)


class IdentityIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    theme_tokens: dict | None = None


class SectionUpdateIn(BaseModel):
    section_id: str = Field(min_length=1)
    props: dict


class RollbackIn(BaseModel):
    version_id: str = Field(min_length=1)


def _template_out(manifest) -> dict:  # noqa: ANN001
    return {
        "id": manifest.id,
        "name": manifest.name,
        "name_ar": manifest.name_ar,
        "description": manifest.description,
        "description_ar": manifest.description_ar,
        "price": _money(manifest.price),
        "currency": purchase_service.PLATFORM_CURRENCY,
        "preview_image": manifest.preview_image,
    }


@router.get("/website/templates")
async def list_templates(_: TenantCtxDep) -> dict:
    return {"templates": [_template_out(m) for m in catalog.list()]}


@router.get("/website/overview")
async def overview(ctx: TenantCtxDep) -> dict:
    result = await content_service.overview(ctx.session, ctx)
    if result.get("state") == "pending" and result.get("pending_purchase"):
        result["payment_instructions"] = get_settings().website_purchase_instructions or None
    return result


@router.post("/website/purchase")
async def create_purchase(body: PurchaseIn, ctx: TenantCtxDep) -> dict:
    purchase = await purchase_service.create(
        ctx.session,
        ctx,
        template_id=body.template_id,
        site_name=body.site_name,
        slug=body.slug,
        payment_reference=body.payment_reference,
    )
    return {
        "purchase": {
            "id": str(purchase.id),
            "template_id": purchase.template_id,
            "status": purchase.status,
            "site_name": purchase.site_name,
            "slug": purchase.slug,
            "price": _money(purchase.price),
            "currency": purchase.currency,
            "payment_reference": purchase.payment_reference,
        }
    }


@router.post("/website/purchase/payment-reference")
async def save_payment_reference(body: PaymentReferenceIn, ctx: TenantCtxDep) -> dict:
    purchase = await purchase_service.set_payment_reference(
        ctx.session, ctx, reference=body.reference
    )
    return {"purchase": {"id": str(purchase.id), "payment_reference": purchase.payment_reference}}


@router.post("/website/purchase/cancel")
async def cancel_purchase(ctx: TenantCtxDep) -> dict:
    purchase = await purchase_service.cancel(ctx.session, ctx)
    return {"purchase": {"id": str(purchase.id), "status": purchase.status}}


@router.get("/website/editor-schema")
async def editor_schema(_: TenantCtxDep) -> dict:
    return {"sections": content_service.editor_schema()}


@router.get("/website/content")
async def get_content(ctx: TenantCtxDep) -> dict:
    return await content_service.get_content(ctx.session, ctx)


@router.post("/website/content/identity")
async def update_identity(body: IdentityIn, ctx: TenantCtxDep) -> dict:
    return await content_service.update_identity(
        ctx.session, ctx, name=body.name, theme_tokens=body.theme_tokens
    )


@router.post("/website/content/section")
async def update_section(body: SectionUpdateIn, ctx: TenantCtxDep) -> dict:
    return await content_service.update_section(
        ctx.session,
        ctx,
        section_id=_uuid(body.section_id, what="section_id"),
        props=body.props,
    )


@router.post("/website/publish")
async def publish(ctx: TenantCtxDep) -> dict:
    result = await content_service.overview(ctx.session, ctx)
    website = result.get("website")
    if not website:
        raise NotFoundError("this workspace has no website")
    return await publish_website(
        ctx.session, tenant_id=ctx.tenant_id, website_id=uuid.UUID(website["id"])
    )


@router.post("/website/rollback")
async def rollback(body: RollbackIn, ctx: TenantCtxDep) -> dict:
    result = await content_service.overview(ctx.session, ctx)
    website = result.get("website")
    if not website:
        raise NotFoundError("this workspace has no website")
    return await rollback_website(
        ctx.session,
        tenant_id=ctx.tenant_id,
        website_id=uuid.UUID(website["id"]),
        version_id=_uuid(body.version_id, what="version_id"),
    )


@router.get("/website/versions")
async def list_versions(ctx: TenantCtxDep) -> dict:
    return {"versions": await content_service.versions(ctx.session, ctx)}


# ---------------------------------------------------------------------------
# Platform-admin purchase queue (owner console)
# ---------------------------------------------------------------------------


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@router.get("/owner/website-purchases")
async def owner_list_purchases(ctx: TenantCtxDep) -> dict:
    """The purchase queue, read through the SECURITY DEFINER function — the
    admin session has no tenant GUC and no tenant policy is weakened."""
    _require_console_admin(ctx)
    session = ctx.session
    rows = (
        (await session.execute(text("SELECT * FROM public.admin_website_purchases()")))
        .mappings()
        .all()
    )
    tenant_ids = {row["tenant_id"] for row in rows}
    names: dict[uuid.UUID, str] = {}
    if tenant_ids:
        names = dict(
            (
                await session.execute(
                    sa.select(Tenant.id, Tenant.name).where(Tenant.id.in_(tenant_ids))
                )
            ).all()
        )
    return {
        "items": [
            {
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "tenant_name": names.get(row["tenant_id"]),
                "template_id": row["template_id"],
                "status": row["status"],
                "price": _money(row["price"]),
                "currency": row["currency"],
                "site_name": row["site_name"],
                "slug": row["slug"],
                "payment_reference": row["payment_reference"],
                "website_id": str(row["website_id"]) if row["website_id"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "confirmed_at": row["confirmed_at"].isoformat() if row["confirmed_at"] else None,
            }
            for row in rows
        ]
    }


@router.post("/owner/website-purchases/{purchase_id}/confirm")
async def owner_confirm_purchase(purchase_id: str, ctx: TenantCtxDep) -> dict:
    _require_console_admin(ctx)
    return await purchase_service.confirm(
        ctx.session,
        purchase_id=_uuid(purchase_id, what="purchase_id"),
        confirmed_by_user_id=ctx.user.id,
    )


@router.post("/owner/website-purchases/{purchase_id}/reject")
async def owner_reject_purchase(purchase_id: str, body: RejectIn, ctx: TenantCtxDep) -> dict:
    _require_console_admin(ctx)
    return await purchase_service.reject(
        ctx.session,
        purchase_id=_uuid(purchase_id, what="purchase_id"),
        confirmed_by_user_id=ctx.user.id,
        reason=body.reason,
    )


# ---------------------------------------------------------------------------
# Public surface (root-level, unauthenticated)
# ---------------------------------------------------------------------------


def _html(body: str) -> Response:
    return Response(content=body, media_type="text/html; charset=utf-8")


async def _serve_site(session: DbSession, *, slug: str | None, hostname: str | None) -> Response:
    site = await public_service.load_snapshot(session, slug=slug, hostname=hostname)
    if site is None:
        raise NotFoundError("site not found")
    return _html(await public_service.render_html(session, site))


@public_sites_router.get("/sites/preview/{template_id}")
async def public_site_preview(template_id: str) -> Response:
    """The template preview walk: the FULL demo site — no database, no
    purchase. Every page is walkable at /sites/preview/<id>/<page-slug>."""
    html = preview_service.render_template_preview(template_id)
    if html is None:
        raise NotFoundError("template not found")
    return _html(html)


@public_sites_router.get("/sites/preview/{template_id}/{page_slug}")
async def public_site_preview_page(template_id: str, page_slug: str) -> Response:
    html = preview_service.render_template_preview(template_id, page_slug=page_slug)
    if html is None:
        raise NotFoundError("template or page not found")
    return _html(html)


def _preview_prefix_from_request(request: Request, template_id: str) -> str:
    """The absolute walk base for the /api/v1-served preview.

    Production reaches the API through the frontend origin's proxy, so the
    links inside the demo document must be ABSOLUTE to the origin the
    visitor opened — derived from the forwarded Host/Proto (never from
    app base_url, which is the loopback bind behind the proxy)."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost"
    return f"{proto}://{host}/api/v1/public/preview/{template_id}"


@router.get("/public/preview/{template_id}")
async def api_public_site_preview(template_id: str, request: Request) -> Response:
    html = preview_service.render_template_preview(
        template_id,
        url_prefix=_preview_prefix_from_request(request, template_id),
    )
    if html is None:
        raise NotFoundError("template not found")
    return _html(html)


@router.get("/public/preview/{template_id}/{page_slug}")
async def api_public_site_preview_page(
    template_id: str, page_slug: str, request: Request
) -> Response:
    html = preview_service.render_template_preview(
        template_id,
        page_slug=page_slug,
        url_prefix=_preview_prefix_from_request(request, template_id),
    )
    if html is None:
        raise NotFoundError("template or page not found")
    return _html(html)


@public_sites_router.get("/sites/{slug}")
async def public_site(slug: str, session: DbSession) -> Response:
    if slug == "preview":
        # Guard the namespace: a published site may never be named "preview".
        raise NotFoundError("site not found")
    return await _serve_site(session, slug=slug, hostname=None)


@public_sites_router.get("/")
async def public_site_root(request: Request, session: DbSession) -> Response:
    """Subdomain mode: ``{slug}.<websites_served_domain>`` resolves the site.

    Off when ``websites_served_domain`` is empty (the default until wildcard
    DNS + TLS are configured) — then this route is an honest 404 and never
    guesses from an untrusted Host header.
    """
    served = (get_settings().websites_served_domain or "").strip().lower()
    host = (request.headers.get("host") or "").split(":", 1)[0].strip().lower()
    if not served or not host.endswith(f".{served}"):
        raise NotFoundError("not found")
    label = host[: -(len(served) + 1)]
    if not label or "." in label:
        raise NotFoundError("not found")
    site = await public_service.load_snapshot(session, hostname=host)
    if site is None:
        site = await public_service.load_snapshot(session, slug=label)
    if site is None:
        raise NotFoundError("site not found")
    return _html(await public_service.render_html(session, site))
