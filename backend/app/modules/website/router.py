"""«My Website» section endpoints (§206 Business System Integration UX).

Every endpoint is tenant-gated (TenantCtxDep): the merchant's Sales OS
identity drives everything — the partner key stays server-side. The tenant id
is the external id the Website Platform knows the merchant by.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.core.errors import ValidationError
from app.modules.identity.deps import TenantCtxDep
from app.modules.identity.models import Tenant, User
from app.modules.website import client as wp

router = APIRouter(tags=["website"])


def _wp_error(exc: wp.WebsitePlatformError) -> HTTPException:
    status = exc.status if exc.status < 500 else 502
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message, "details": exc.details})


async def _tenant_name(session, tenant_id: uuid.UUID) -> str:
    tenant = await session.get(Tenant, tenant_id)
    return tenant.name if tenant and tenant.name else f"salesos-{tenant_id}"


async def _user_email(session, user_id: uuid.UUID) -> str:
    """AuthedUser carries no email claim — read it from the users row."""
    user = await session.get(User, user_id)
    if not user or not user.email:
        raise ValidationError("authenticated user email is required")
    return user.email


@router.get("/website/overview")
async def overview(ctx: TenantCtxDep):
    """One call for the section: whether the tenant has a website, its
    status, and (when provisioned) publish/usage data. Products come from the
    tenant catalog automatically via the platform's sales-os binding."""
    try:
        status = await wp.resolve_website(str(ctx.tenant_id))
        usage = await wp.usage(status["organizationId"])
        return {"provisioned": True, "website": status, "usage": usage}
    except wp.WebsitePlatformError as exc:
        if exc.status == 404:
            templates = await wp.templates()
            return {"provisioned": False, "templates": templates}
        raise _wp_error(exc) from exc


@router.post("/website/provision")
async def provision(body: dict, ctx: TenantCtxDep):
    template_id = body.get("template_id")
    if not template_id:
        raise ValidationError("template_id is required")
    email = await _user_email(ctx.session, ctx.user.id)
    try:
        tenant_name = await _tenant_name(ctx.session, ctx.tenant_id)
        result = await wp.provision_website(
            email=email,
            external_tenant_id=str(ctx.tenant_id),
            tenant_name=tenant_name,
            website_name=body.get("website_name") or tenant_name,
            template_id=template_id,
            display_name=None,
        )
        status = await wp.resolve_website(str(ctx.tenant_id))
        return {"provisioned": True, "website": status, "provisionResult": result}
    except wp.WebsitePlatformError as exc:
        raise _wp_error(exc) from exc


@router.post("/website/session")
async def session(ctx: TenantCtxDep):
    """SSO: returns a platform session token + Studio URL. The frontend stores
    the token (localStorage `wp_token`) and opens the Studio in a new tab —
    the merchant lands inside the builder already signed in."""
    email = await _user_email(ctx.session, ctx.user.id)
    try:
        result = await wp.sso_session(email=email)
        return {"token": result["token"], "expiresAt": result.get("expiresAt"), "studioUrl": result.get("studioUrl")}
    except wp.WebsitePlatformError as exc:
        raise _wp_error(exc) from exc


@router.post("/website/publish")
async def publish(ctx: TenantCtxDep):
    try:
        status = await wp.resolve_website(str(ctx.tenant_id))
        result = await wp.publish(status["websiteId"])
        return {"ok": True, "releaseId": result.get("releaseId"), "website": status}
    except wp.WebsitePlatformError as exc:
        if exc.status == 409:
            return {"ok": False, "code": exc.code, "message": exc.message, "details": exc.details}
        raise _wp_error(exc) from exc


@router.get("/website/products-count")
async def products_count(ctx: TenantCtxDep):
    """How many published products the merchant has — shown in the section so
    the merchant knows what the website will display."""
    from sqlalchemy import func, select

    from app.modules.catalog.models import Product

    count = (
        await ctx.session.execute(
            select(func.count()).select_from(Product).where(Product.tenant_id == ctx.tenant_id, Product.status == "published")
        )
    ).scalar()
    return {"publishedProducts": int(count or 0)}
