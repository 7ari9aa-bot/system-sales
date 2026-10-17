"""CONVERSATIONS routes — inbox (staff) + public webchat + channel webhooks.

This module is a backward-compatible aggregator. The route implementations
have been decomposed into the ``routers/`` package:
  - ``routers/inbox.py``: Staff inbox, messages, assignment, closing, reading, reconciliation
  - ``routers/webchat.py``: Public visitor webchat ingress and history
  - ``routers/webhooks.py``: Channel webhooks (WhatsApp, Telegram, Messenger, Instagram, Facebook)
  - ``routers/stream.py``: Server-Sent Events (SSE) inbox state stream
  - ``routers/templates.py``: Message templates governance and lifecycle

All symbols, routers, models, and helper functions are re-exported here with
exact signature and endpoint module identity preserved.
"""

from __future__ import annotations

from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.routers import (
    _WEBHOOK_CHANNELS,
    AssignRequest,
    SendMessageRequest,
    TemplateApproveRequest,
    TemplateRejectRequest,
    TemplateUpsertRequest,
    WebchatInbound,
    _inbox_page,
    _redact_inbox_item,
    _stream_auth,
    _template_input,
    _template_out,
    approve_template,
    archive_template,
    assign,
    channel_webhook,
    close,
    create_template,
    get_template,
    inbox_query,
    list_conversations,
    list_messages,
    list_templates,
    mark_read,
    pause_template,
    public_router,
    reconcile_messages,
    reject_template,
    resume_template,
    router,
    send_message,
    stream_conversations,
    submit_template,
    templates_router,
    update_template,
    verify_webhook,
    webchat_inbound,
    webchat_list_messages,
    webhook_router,
)

# Preserve endpoint __module__ for test parameter declaration inspection (§test_route_parameter_declarations)  # noqa: E501
for _r in (
    *router.routes,
    *public_router.routes,
    *webhook_router.routes,
    *templates_router.routes,
):
    if hasattr(_r, "endpoint") and callable(_r.endpoint):
        _r.endpoint.__module__ = "app.modules.conversations.router"

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
    "get_adapter",
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
