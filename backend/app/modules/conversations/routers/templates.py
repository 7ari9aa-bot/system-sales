"""Message templates governance and lifecycle management routes (§31)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.conversations.routers._deps import TenantContext, require_permission
from app.modules.conversations.templates import TemplateInput, TemplateService

templates_router = APIRouter(prefix="/message-templates", tags=["templates"])


class TemplateUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    body_text: str = Field(min_length=1, max_length=4096)
    language: str = Field(default="ar", max_length=15)
    provider: str = Field(default="whatsapp", max_length=31)
    variables: list[str] = Field(default_factory=list)


class TemplateRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class TemplateApproveRequest(BaseModel):
    provider_template_id: str | None = Field(default=None, max_length=127)


def _template_out(t) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "status": t.status,
        "language": t.language,
        "provider": t.provider,
        "body_text": t.body_text,
        "variables": t.variables or [],
        "provider_template_id": t.provider_template_id,
        "version": t.version,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _template_input(body: TemplateUpsertRequest) -> TemplateInput:
    return TemplateInput(
        name=body.name,
        body_text=body.body_text,
        language=body.language,
        provider=body.provider,
        variables=tuple(body.variables),
    )


@templates_router.get("")
async def list_templates(
    ctx: TenantContext = Depends(require_permission("conversations:read")),
    status: str | None = None,
    provider: str | None = None,
):
    rows = await TemplateService.list_templates(
        ctx.session, ctx.tenant_id, status=status, provider=provider
    )
    return {"items": [_template_out(t) for t in rows]}


@templates_router.post("", status_code=201)
async def create_template(
    body: TemplateUpsertRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Creates a DRAFT — not sendable until it is submitted and approved."""
    template = await TemplateService.create(ctx.session, ctx.tenant_id, _template_input(body))
    return _template_out(template)


@templates_router.get("/{template_id}")
async def get_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    return _template_out(await TemplateService.get(ctx.session, ctx.tenant_id, template_id))


@templates_router.put("/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpsertRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Only draft/rejected templates are editable — see TemplateService."""
    template = await TemplateService.update(
        ctx.session, ctx.tenant_id, template_id, _template_input(body)
    )
    return _template_out(template)


@templates_router.post("/{template_id}/submit")
async def submit_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    template = await TemplateService.submit(ctx.session, ctx.tenant_id, template_id)
    return _template_out(template)


@templates_router.post("/{template_id}/approve")
async def approve_template(
    template_id: uuid.UUID,
    body: TemplateApproveRequest | None = None,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Approval is a governance action, so it needs settings:write — not the
    same permission as writing a message."""
    template = await TemplateService.approve(
        ctx.session,
        ctx.tenant_id,
        template_id,
        reviewer=str(ctx.user.id),
        provider_template_id=body.provider_template_id if body else None,
    )
    return _template_out(template)


@templates_router.post("/{template_id}/reject")
async def reject_template(
    template_id: uuid.UUID,
    body: TemplateRejectRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    template = await TemplateService.reject(
        ctx.session,
        ctx.tenant_id,
        template_id,
        reason=body.reason,
        reviewer=str(ctx.user.id),
    )
    return _template_out(template)


@templates_router.post("/{template_id}/pause")
async def pause_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    return _template_out(await TemplateService.pause(ctx.session, ctx.tenant_id, template_id))


@templates_router.post("/{template_id}/resume")
async def resume_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    return _template_out(await TemplateService.resume(ctx.session, ctx.tenant_id, template_id))


@templates_router.post("/{template_id}/archive")
async def archive_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    return _template_out(await TemplateService.archive(ctx.session, ctx.tenant_id, template_id))
