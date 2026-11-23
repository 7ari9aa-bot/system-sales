"""Reading back what happened before the channel was connected.

Meta's Conversation API is the only place a Page can see the threads it already had: a webhook
only ever delivers what happens AFTER the subscription, so a store that connects today has an empty
inbox even though customers wrote last week. This module walks that API with explicit, deliberate
caps so one connect can never turn into an unbounded crawl of a Page's whole history.

Idempotency is a property of the RESULT, not of a stored cursor: every record carries Meta's own
stable ids (conversation id, message id), so running the walk twice yields the same records and the
caller can dedupe by those ids. That is what makes a backfill safe to retry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.errors import ExternalProviderError

logger = logging.getLogger(__name__)

_API_VERSION = "v23.0"

#: The caps. Meta allows 100 per page; we ask for less and stop early, so a busy Page cannot
#: exhaust the app's rate limit in one connect.
DEFAULT_PAGE_SIZE = 25
DEFAULT_MAX_CONVERSATIONS = 100
DEFAULT_MAX_PAGES = 5

_CONVERSATION_FIELDS = "id,updated_time,message_count,participants,unread_count,snippet"
_MESSAGE_FIELDS = "id,created_time,from,to,message"


@dataclass
class BackfillResult:
    """What the walk actually returned, with the reason it stopped."""

    conversations: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: The same messages, kept per thread. A message object does not name its conversation, so a
    #: flat list cannot be filed into the right thread afterwards; this is what the writer reads.
    messages_by_conversation: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    pages_read: int = 0
    #: "exhausted" (Meta had nothing more), "capped" (our limit), or "error".
    stopped: str = "exhausted"
    error: str | None = None

    @property
    def conversation_ids(self) -> list[str]:
        return [str(c.get("id")) for c in self.conversations if c.get("id")]

    @property
    def message_ids(self) -> list[str]:
        return [str(m.get("id")) for m in self.messages if m.get("id")]


class MessengerBackfill:
    """A capped, retryable walk of the Page's conversations."""

    def __init__(self, *, api_version: str = _API_VERSION) -> None:
        self._base = f"https://graph.facebook.com/{api_version}"

    async def _get(
        self, http: httpx.AsyncClient, url: str, token: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        resp = await http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ExternalProviderError(f"messenger backfill: not JSON ({resp.status_code})") from exc
        if not isinstance(payload, dict):
            raise ExternalProviderError("messenger backfill: unexpected payload")
        err = payload.get("error")
        if resp.status_code >= 500 or resp.status_code == 429 or isinstance(err, dict):
            # A rate limit or an outage is retryable; carrying the reason lets the caller say so.
            message = err.get("message") if isinstance(err, dict) else None
            raise ExternalProviderError(
                f"messenger backfill: {resp.status_code} {message or ''}".strip()
            )
        return payload

    async def walk(
        self,
        http: httpx.AsyncClient,
        *,
        page_id: str,
        token: str,
        with_messages: bool = True,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> BackfillResult:
        """Read up to the caps and say which cap stopped it."""
        result = BackfillResult()
        url = f"{self._base}/{page_id}/conversations"
        params: dict[str, Any] | None = {
            "fields": _CONVERSATION_FIELDS,
            "limit": max(1, min(page_size, 100)),
        }

        while True:
            if result.pages_read >= max_pages:
                result.stopped = "capped"
                break
            try:
                payload = await self._get(http, url, token, params)
            except ExternalProviderError as exc:
                result.stopped = "error"
                result.error = str(exc)
                logger.warning("messenger.backfill_stopped error=%s", exc)
                break
            result.pages_read += 1
            for conversation in payload.get("data") or []:
                if len(result.conversations) >= max_conversations:
                    result.stopped = "capped"
                    break
                result.conversations.append(conversation)
            if result.stopped == "capped":
                break

            next_url = ((payload.get("paging") or {}).get("next")) or None
            if not next_url:
                result.stopped = "exhausted"
                break
            url, params = next_url, None

        if with_messages:
            for conversation in result.conversations:
                cid = str(conversation.get("id") or "")
                if not cid:
                    continue
                try:
                    payload = await self._get(
                        http,
                        f"{self._base}/{cid}/messages",
                        token,
                        {"fields": _MESSAGE_FIELDS, "limit": max(1, min(page_size, 100))},
                    )
                except ExternalProviderError as exc:
                    # One unreadable thread must not throw away the conversations already read.
                    logger.warning("messenger.backfill_messages_failed conversation=%s", cid)
                    result.error = result.error or str(exc)
                    continue
                batch = payload.get("data") or []
                result.messages.extend(batch)
                result.messages_by_conversation[cid] = batch
        return result
