"""Shared dependencies, request models, and redaction helpers for conversation routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.field_auth import PII_FIELDS, redact_fields
from app.modules.conversations.inbox import encode_keyset

# Re-exports: the sibling routers import their identity dependencies from
# here (the aggregator contract) — the alias form marks them as deliberate
# re-exports so a lint sweep cannot read them as dead and break the chain.
from app.modules.identity.deps import (  # noqa: F401
    AuthedUser as AuthedUser,
)
from app.modules.identity.deps import (
    DbSession as DbSession,
)
from app.modules.identity.deps import (
    TenantContext as TenantContext,
)
from app.modules.identity.deps import (
    TenantCtxDep as TenantCtxDep,
)
from app.modules.identity.deps import (
    require_permission as require_permission,
)
from app.modules.identity.deps import (
    tenant_may_use_api as tenant_may_use_api,
)

# ---------- staff inbox request schemas ----------


class SendMessageRequest(BaseModel):
    """§30: outside the customer-service window a free-form reply is refused,
    so the caller must supply an APPROVED template instead."""

    body: str | None = Field(default=None, max_length=4096)
    template_name: str | None = Field(default=None, max_length=127)
    template_vars: dict | None = None
    template_language: str = Field(default="ar", max_length=15)
    # The message being replied to (our messages.id). Optional; checked against
    # the conversation in the route.
    reply_to_message_id: uuid.UUID | None = None
    # An upload from POST /conversations/{id}/media. `body` then becomes its
    # caption (images, videos and documents only).
    media_id: uuid.UUID | None = None
    # Instagram only: send the heart sticker, or one of the shop's own posts (its media id) as a
    # card. Neither carries free text, so neither needs `body`.
    instagram_heart: bool = False
    instagram_share_post_id: str | None = Field(default=None, max_length=64)


class ReadSignalRequest(BaseModel):
    """Opening a chat sends the read receipt; typing adds the "typing…" indicator."""

    typing: bool = False


class ReactionRequest(BaseModel):
    """An emoji reaction to one message. An empty emoji withdraws our reaction."""

    emoji: str = Field(default="", max_length=16)


class ListStateRequest(BaseModel):
    """Shared list flags for one conversation. Only the fields sent change.

    ``mute`` is a duration: "8h" | "1w" | "always" | "off". Anything else is a
    validation error, so the client can never write an arbitrary date.
    """

    pinned: bool | None = None
    archived: bool | None = None
    marked_unread: bool | None = None
    mute: Literal["8h", "1w", "always", "off"] | None = None


class AssignRequest(BaseModel):
    user_id: uuid.UUID | None = None


# §146 on the inbox surface. The read model ships the customer's phone under
# ``customer_phone``, which is NOT the bare ``phone`` key ``PII_FIELDS`` names —
# so ``redact_fields``' default set would walk past it and leak the number. The
# explicit set is applied only when the caller lacks ``pii:read``, because
# ``redact_fields`` with ``fields_to_redact`` redacts UNCONDITIONALLY; the same
# shape ``customers/router.py:_redact_issue_item`` settled on for the same trap.
# The handle and the photo identify a person as surely as a phone number does.
_INBOX_PII_FIELDS = PII_FIELDS | frozenset(
    {"customer_phone", "customer_handle", "customer_avatar_url"}
)


def _redact_inbox_item(item: dict, *, permission_codes: set[str]) -> dict:
    """One inbox row as the caller is allowed to see it (§146)."""
    if "pii:read" in permission_codes:
        return dict(item)
    return redact_fields(
        item, permission_codes=permission_codes, fields_to_redact=_INBOX_PII_FIELDS
    )


def _inbox_page(items: list[dict], limit: int) -> tuple[list[dict], str | None]:
    """Split a ``limit + 1`` fetch into ``(page, next_cursor)``.

    The cursor is the page's own SORT KEY, not ``created_at``: the read model
    orders by ``last_message_at DESC NULLS LAST``, and paging on any other
    column skips or repeats rows the moment the two disagree — which they do on
    every active conversation. ``None`` is load-bearing for the never-messaged
    tail; see ``inbox.encode_keyset``.
    """
    if len(items) <= limit:
        return items, None
    boundary = items[limit - 1]
    # The row's own sort key, NULL included. Falling back to ``created_at``
    # here would hand ``InboxQuery.page`` a DATED cursor for a tail row, which
    # re-admits every dated row that sorts above it — the duplication this
    # whole branch exists to avoid, arriving one page in.
    at = boundary["last_message_at"]
    return items[:limit], encode_keyset(
        datetime.fromisoformat(at) if at else None, uuid.UUID(boundary["id"])
    )
