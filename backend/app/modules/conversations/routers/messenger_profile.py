"""Messenger Platform settings: greeting, Get Started, persistent menu, ice breakers, labels.

`MessengerProfile` (gateway/messenger_profile.py) has been written and tested since the first
Messenger pass, but nothing called it: the merchant could not set any of these from FIHRIST, so
the Page's Messenger profile stayed whatever it was in Meta Business Suite. The report listed the
whole settings lifecycle as missing for that reason, and this router is what makes it exist.

The split is deliberate and matches the rest of the module:

* Messenger is its own function with its own permission (`pages_messaging`), so these routes refuse
  with an explanation when the Page connection never granted it — they do not borrow Facebook's
  Page-management permission to reach Messenger.
* Meta is called FIRST and our row changes only after it answers. A greeting that Meta refused must
  never look saved here.
* Nothing is invented for the merchant: `GET` reads what Meta holds, so a screen shows the truth
  including settings made outside FIHRIST.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.modules.conversations.gateway.facebook_pages import page_token_and_id
from app.modules.conversations.gateway.messenger_profile import MessengerProfile
from app.modules.conversations.routers._deps import TenantContext, require_permission
from app.modules.conversations.routers.inbox import (
    _allowed_channels,
    _channel_config,
    _sendable_channels,
)
from app.modules.customers.meta_scopes import missing_private_reply_scopes

router = APIRouter(tags=["messenger"])

_PROVIDER = "messenger"

#: The settings this router manages. Meta stores each under its own name in `me/messenger_profile`.
SETTINGS = ("greeting", "get_started", "persistent_menu", "ice_breakers")


class GreetingBody(BaseModel):
    text: str = Field(min_length=1, max_length=160)
    locale: str = Field(default="default", max_length=20)


class GetStartedBody(BaseModel):
    payload: str = Field(default="GET_STARTED", min_length=1, max_length=64)


class PersistentMenuBody(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=5)
    locale: str = Field(default="default", max_length=20)
    composer_input_disabled: bool = False


class IceBreakersBody(BaseModel):
    questions: list[dict] = Field(min_length=1, max_length=3)
    locale: str = Field(default="default", max_length=20)


_BODIES = {
    "greeting": GreetingBody,
    "get_started": GetStartedBody,
    "persistent_menu": PersistentMenuBody,
    "ice_breakers": IceBreakersBody,
}


async def _credentials(ctx: TenantContext, *, send: bool) -> dict:
    """The Messenger channel's Page token, with the channel and send gates applied first."""
    allowed = await _allowed_channels(ctx)
    if allowed is not None and _PROVIDER not in allowed:
        raise PermissionDeniedError("channel is not enabled for this user")
    if send:
        sendable = await _sendable_channels(ctx)
        if sendable is not None and _PROVIDER not in sendable:
            raise PermissionDeniedError("sending is not enabled for this user on this channel")
    config = await _channel_config(ctx, _PROVIDER)
    token, page_id = page_token_and_id(config or {})
    if not token or not page_id:
        raise ConflictError("Messenger is not connected")
    # Changing the Page's Messenger profile IS a Messenger call: without `pages_messaging` Meta
    # refuses it, so the store is told which permission to grant instead of seeing a Meta error.
    if send and missing_private_reply_scopes((config or {}).get("granted_scopes")):
        raise PermissionDeniedError(
            "Messenger profile settings need the pages_messaging permission; "
            "reconnect the Page and accept it"
        )
    return config or {}


def _http(request: Request) -> httpx.AsyncClient:
    client = getattr(request.app.state, "http", None)
    if client is None:  # pragma: no cover - the app always installs one
        raise ConflictError("outbound HTTP client is not available")
    return client


@router.get("/messenger/profile")
async def read_profile(
    request: Request, ctx: TenantContext = Depends(require_permission("conversations:read"))
):
    """The Page's Messenger profile as Meta holds it, not as we last wrote it."""
    config = await _credentials(ctx, send=False)
    token, _page_id = page_token_and_id(config)
    profile = await MessengerProfile().get_profile(
        _http(request), token=token, fields=list(SETTINGS)
    )
    data = profile.get("data") or [{}]
    first = data[0] if isinstance(data, list) and data else {}
    return {"settings": {key: first.get(key) for key in SETTINGS}}


@router.put("/messenger/profile/{setting}")
async def write_profile(
    setting: str,
    body: dict,
    request: Request,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Set one Messenger profile setting. Meta answers first, so a refusal is never "saved"."""
    if setting not in _BODIES:
        raise ValidationError(f"إعداد غير معروف: {setting}")
    try:
        parsed = _BODIES[setting](**body)
    except PydanticValidationError as exc:
        # Meta's own limits (160 chars of greeting, 5 menu items, 3 ice breakers) are checked
        # here, so a bad shape is a 400 with a reason instead of a 500 or a Meta refusal.
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", []))
        raise ValidationError(f"إعداد {setting} غير صالح: {first.get('msg')} ({where})") from exc
    config = await _credentials(ctx, send=True)
    token, _page_id = page_token_and_id(config)
    client = _http(request)
    profile = MessengerProfile()

    if setting == "greeting":
        await profile.set_greeting(client, token=token, text=parsed.text, locale=parsed.locale)
    elif setting == "get_started":
        await profile.set_get_started(client, token=token, payload=parsed.payload)
    elif setting == "persistent_menu":
        await profile.set_persistent_menu(
            client,
            token=token,
            items=parsed.items,
            locale=parsed.locale,
            composer_input_disabled=parsed.composer_input_disabled,
        )
    else:
        await profile.set_ice_breakers(
            client, token=token, questions=parsed.questions, locale=parsed.locale
        )
    return {"setting": setting, "saved": True}


@router.delete("/messenger/profile/{setting}")
async def clear_profile(
    setting: str,
    request: Request,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Remove one setting. Meta has no per-field delete endpoint; it takes a field list."""
    if setting not in SETTINGS:
        raise ValidationError(f"إعداد غير معروف: {setting}")
    config = await _credentials(ctx, send=True)
    token, _page_id = page_token_and_id(config)
    await MessengerProfile().delete_fields(_http(request), token=token, fields=[setting])
    return {"setting": setting, "cleared": True}


# ── conversation labels ────────────────────────────────────────────────────────────────────────
# Meta's own labels on one customer's thread (`custom_labels` on the PSID). They live in Messenger,
# not in our database, so two staff members on two devices see the same label — and the label is
# visible in Meta's own inbox too. Same rule as the profile: no `pages_messaging`, no call.


class LabelsRequest(BaseModel):
    """The labels to add or remove on one thread."""

    labels: list[str] = Field(min_length=1, max_length=20)
    psid: str | None = Field(
        default=None,
        description="The customer's Page-scoped id; when omitted the conversation's own is used",
    )


@router.post("/messenger/labels/{conversation_id}")
async def add_labels(
    conversation_id: str,
    body: LabelsRequest,
    request: Request,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Attach labels to one conversation, in Meta, where the owner's other tools see them."""
    # The permission is checked BEFORE the thread is even looked up: a caller without
    # `pages_messaging` must be refused for that reason, not told whether the id exists.
    config = await _credentials(ctx, send=True)
    psid = await _psid(ctx, conversation_id, body.psid)
    token, _page_id = page_token_and_id(config)
    await MessengerProfile().add_labels(_http(request), token=token, psid=psid, labels=body.labels)
    return {"conversation_id": conversation_id, "labels": body.labels, "saved": True}


@router.delete("/messenger/labels/{conversation_id}")
async def remove_labels(
    conversation_id: str,
    body: LabelsRequest,
    request: Request,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Remove labels from one conversation."""
    config = await _credentials(ctx, send=True)
    psid = await _psid(ctx, conversation_id, body.psid)
    token, _page_id = page_token_and_id(config)
    await MessengerProfile().remove_labels(
        _http(request), token=token, psid=psid, labels=body.labels
    )
    return {"conversation_id": conversation_id, "labels": body.labels, "cleared": True}


async def _psid(ctx: TenantContext, conversation_id: str, given: str | None) -> str:
    """The PSID to label: the one the caller named, or the conversation's own identity.

    Reading it from the conversation instead of trusting the browser matters: a PSID typed into a
    request could label somebody else's thread, and Meta would do it, because the Page token has
    that power. The PSID is the customer's Messenger identity (`customer_identities`), which is the
    same row `read_signal_service` reads for mark_seen.
    """
    if given:
        return given
    from app.modules.conversations.customer_profile import customers
    from app.modules.conversations.models import Conversation

    conversation = await ctx.session.get(Conversation, _uuid(conversation_id))
    if conversation is None or conversation.tenant_id != ctx.tenant_id:
        raise NotFoundError("المحادثة غير موجودة")
    if str(conversation.channel) != "messenger":
        raise ValidationError("التسميات على ميتا للماسنجر بس؛ القناة دي ملهاش تسميات هناك")
    identity = await customers().channel_identity(
        ctx.session, ctx.tenant_id, conversation.customer_id, "messenger"
    )
    if identity is None or not identity.external_id:
        raise ValidationError("مفيش هوية ماسنجر للعميل ده، فمش ممكن نوسم المحادثة")
    return str(identity.external_id)


def _uuid(value: str):
    import uuid as _uuid_module

    try:
        return _uuid_module.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError("معرّف محادثة غير صالح") from exc


__all__ = ["router", "SETTINGS"]
