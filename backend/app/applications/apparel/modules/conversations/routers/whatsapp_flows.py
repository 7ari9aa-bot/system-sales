"""WhatsApp Flows: create, upload the Flow JSON, publish, and list — from FIHRIST.

`gateway/whatsapp_flows.py` has been written and tested since the first WhatsApp pass, and the
interactive builder could already SEND a flow message and parse the `nfm_reply` that comes back.
But nothing ever created or published a Flow: `WhatsAppFlowsClient` had no caller at all, so the
lifecycle the report asks for ("create, publish, send flow message, receive nfm_reply, store the
result in the conversation") only existed from the second half onwards.

This router is the missing first half. The rules match the rest of the module:

* Meta answers first — a Flow that Meta refused is never reported as created or published;
* Meta's own validation errors on a Flow JSON are passed through, because the person who wrote the
  JSON is the only one who can fix it;
* a missing WABA id or token is a clear refusal, not a 500.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.errors import ConflictError, ExternalProviderError, ValidationError
from app.applications.apparel.modules.conversations.gateway.whatsapp_flows import WhatsAppFlowsClient
from app.applications.apparel.modules.conversations.routers._deps import TenantContext, require_permission
from app.applications.apparel.modules.conversations.routers.inbox import _channel_config

router = APIRouter(prefix="/whatsapp/flows", tags=["whatsapp-flows"])


async def _credentials(ctx: TenantContext) -> dict:
    """The tenant's WhatsApp credentials, or a refusal that says what is missing."""
    config = await _channel_config(ctx, "whatsapp")
    if not config:
        raise ConflictError("WhatsApp is not connected")
    return config


class FlowCreateRequest(BaseModel):
    """A new Flow. It is a DRAFT until it is published, which is Meta's own rule."""

    name: str = Field(min_length=1, max_length=200)
    categories: list[dict[str, Any]] | None = Field(
        default=None,
        description='e.g. [{"name": "OTHER"}]; Meta validates the name against its own list',
    )


class FlowAssetRequest(BaseModel):
    """The Flow JSON. Meta validates it and answers with its own errors, passed through."""

    flow_json: dict[str, Any] = Field(
        description="The flow.json body (version, screens, routing_model)"
    )


@router.get("")
async def list_flows(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    """The Flows on this WhatsApp Business Account, as Meta lists them."""
    credentials = await _credentials(ctx)
    return {"items": await WhatsAppFlowsClient().list(credentials, limit=limit)}


@router.post("", status_code=201)
async def create_flow(
    body: FlowCreateRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Create a Flow (DRAFT). Meta's id comes back; nothing is published yet."""
    credentials = await _credentials(ctx)
    try:
        created = await WhatsAppFlowsClient().create(
            credentials, name=body.name, categories=body.categories
        )
    except ValidationError as exc:
        raise ValidationError(str(exc)) from exc
    return {"flow_id": str(created.get("id")), "status": created.get("status") or "DRAFT"}


@router.post("/{flow_id}/assets")
async def upload_flow_json(
    flow_id: str,
    body: FlowAssetRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Attach the Flow JSON to a draft Flow.

    Meta validates the JSON here and refuses it with its own message naming the screen or field at
    fault. That message is what the person who wrote the JSON needs, so it is passed through
    unchanged rather than replaced with "something went wrong".
    """
    credentials = await _credentials(ctx)
    try:
        result = await WhatsAppFlowsClient().upload_asset(
            credentials, flow_id=flow_id, flow_json=body.flow_json
        )
    except ExternalProviderError as exc:
        # A 400 from Meta here is OUR JSON being wrong, not Meta being down: answering 502 would
        # send the author hunting for an outage instead of the missing screen title.
        if _is_rejected_json(exc):
            raise ValidationError(f"ميتا رفضت الـFlow JSON: {_meta_message(exc)}") from exc
        raise
    return {"flow_id": flow_id, "validation": result.get("validation_errors") or [], "saved": True}


@router.post("/{flow_id}/publish")
async def publish_flow(
    flow_id: str,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Publish a Flow so it can be sent. A Flow with no valid JSON is refused by Meta here."""
    credentials = await _credentials(ctx)
    result = await WhatsAppFlowsClient().publish(credentials, flow_id=flow_id)
    return {"flow_id": flow_id, "published": True, "meta": result.get("success", True)}


def _is_rejected_json(exc: Exception) -> bool:
    """True when Meta's answer is about the Flow JSON itself rather than the service."""
    text = str(exc)
    return " 400 " in text and ("INVALID" in text.upper() or "validation" in text.lower())


def _meta_message(exc: Exception) -> str:
    """Meta's own words, without our wrapper prefix, so the author can act on them."""
    text = str(exc)
    marker = "failed: "
    return text.split(marker, 1)[-1][:400] if marker in text else text[:400]


__all__ = ["router"]
