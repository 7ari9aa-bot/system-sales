"""Conversations routers package — aggregator for inbox, webchat, webhooks, stream, and templates."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.conversations.routers._deps import (
    AssignRequest,
    SendMessageRequest,
    _inbox_page,
    _redact_inbox_item,
)
from app.modules.conversations.routers.inbox import (
    assign,
    close,
    inbox_query,
    list_conversations,
    list_messages,
    mark_read,
    reconcile_messages,
    router as _inbox_router,
    send_message,
)
from app.modules.conversations.routers.stream import (
    _stream_auth,
    router as _stream_router,
    stream_conversations,
)
from app.modules.conversations.routers.templates import (
    TemplateApproveRequest,
    TemplateRejectRequest,
    TemplateUpsertRequest,
    _template_input,
    _template_out,
    approve_template,
    archive_template,
    create_template,
    get_template,
    list_templates,
    pause_template,
    reject_template,
    resume_template,
    submit_template,
    templates_router,
    update_template,
)
from app.modules.conversations.routers.webchat import (
    WebchatInbound,
    public_router,
    webchat_inbound,
    webchat_list_messages,
)
from app.modules.conversations.routers.webhooks import (
    _WEBHOOK_CHANNELS,
    channel_webhook,
    verify_webhook,
    webhook_router,
)

# Combine inbox and stream routes into the canonical conversations `router`
router = APIRouter(tags=["inbox"])
router.routes.extend(_inbox_router.routes)
router.routes.extend(_stream_router.routes)

__all__ = [
    "AssignRequest",
    "SendMessageRequest",
    "TemplateApproveRequest",
    "TemplateRejectRequest",
    "TemplateUpsertRequest",
    "WebchatInbound",
    "_WEBHOOK_CHANNELS",
    "_inbox_page",
    "_redact_inbox_item",
    "_stream_auth",
    "_template_input",
    "_template_out",
    "approve_template",
    "archive_template",
    "assign",
    "channel_webhook",
    "close",
    "create_template",
    "get_template",
    "inbox_query",
    "list_conversations",
    "list_messages",
    "list_templates",
    "mark_read",
    "pause_template",
    "public_router",
    "reconcile_messages",
    "reject_template",
    "resume_template",
    "router",
    "send_message",
    "stream_conversations",
    "submit_template",
    "templates_router",
    "update_template",
    "verify_webhook",
    "webchat_inbound",
    "webchat_list_messages",
    "webhook_router",
]
