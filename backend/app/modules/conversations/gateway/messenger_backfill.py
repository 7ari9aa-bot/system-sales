"""Backfill Messenger history from Meta, without touching anything a live message would.

A Page that connects Messenger already has conversations, and a webhook outage leaves a gap in
the ones it has. Meta keeps them: ``GET /{page-id}/conversations?platform=messenger`` lists the
threads (each with its participants), and each thread's messages carry a sender, a time, text and
attachments. This module reads them and writes the ones we do not have.

What makes it safe to run on a live shop:

* **It never goes through ``IngestService.ingest``.** That path starts the first-response clock
  and queues ``message.received``, which is what makes the AI answer. A message from last month
  must do neither, so these rows are written directly, the way a Page-inbox echo is.
* **It is idempotent.** A message is keyed by Meta's own id (``Message.channel_message_id``); a
  second run, an overlapping window, or a webhook that already delivered the message writes
  nothing new.
* **It is bounded.** Threads and messages per thread are capped, the window defaults to 90 days,
  and Meta's rate-limit signal stops the run instead of retrying into a block.
* **It never rewinds a thread.** ``last_customer_message_at`` anchors the 24-hour reply window, so
  it only ever moves forward; an old message cannot reopen or close a window a live one set.

Meta lists every message id of a thread but only returns the details of the most recent 20; older
ones come back as a "deleted" error. That is a limit of the API, not a failure, so such a message
is skipped and counted.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CHANNEL = "messenger"
GRAPH_VERSION = "v27.0"
_GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

#: Defaults, all overridable per run. Meta only returns details for a thread's latest 20 messages,
#: so a higher per-thread cap would only ask for messages Meta then refuses.
DEFAULT_DAYS = 90
DEFAULT_MAX_THREADS = 50
DEFAULT_MAX_MESSAGES = 20
#: Page size of the thread list. One run handles one page; the job queues the next from the cursor.
THREAD_PAGE_SIZE = 25
#: Meta's usage header above this percentage means "stop now". 80 leaves room for live traffic.
USAGE_STOP_PERCENT = 80

_MESSAGE_FIELDS = (
    "id,created_time,from,message,attachments{id,mime_type,name,size,image_data,file_url}"
)
_THREAD_FIELDS = "id,updated_time,participants"


class BackfillStopped(Exception):
    """Meta asked us to slow down (rate limit or usage header). The run ends cleanly, resumable."""


@dataclass
class BackfillResult:
    """What one run did. Plain numbers, so the job can store them and the owner can read them."""

    threads_seen: int = 0
    messages_written: int = 0
    messages_known: int = 0
    messages_unreadable: int = 0
    customers_created: int = 0
    next_cursor: str | None = None
    stopped_reason: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "threads_seen": self.threads_seen,
            "messages_written": self.messages_written,
            "messages_known": self.messages_known,
            "messages_unreadable": self.messages_unreadable,
            "customers_created": self.customers_created,
            "next_cursor": self.next_cursor,
            "stopped_reason": self.stopped_reason,
            "errors": self.errors[:5],
        }


# --------------------------------------------------------------------------- pure parsing ---


def parse_time(value: Any) -> datetime | None:
    """Meta writes ``2022-07-12T19:11:07+0000`` (no colon in the offset) or a unix number."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) > 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _kind_of(mime: str) -> str:
    major = mime.split("/", 1)[0].lower() if mime else ""
    if major == "image":
        return "image"
    if major == "video":
        return "video"
    if major == "audio":
        return "voice"
    return "file" if mime else "unsupported"


def _attachment_parts(message: dict) -> list[dict]:
    """One ``{content_type, media_url}`` per attachment Meta lists; ``[]`` when there are none."""
    raw = message.get("attachments")
    items = raw.get("data") if isinstance(raw, dict) else raw
    parts: list[dict] = []
    for att in items or []:
        if not isinstance(att, dict):
            continue
        image = att.get("image_data") if isinstance(att.get("image_data"), dict) else {}
        url = att.get("file_url") or image.get("url") or image.get("preview_url")
        url = url if isinstance(url, str) and url else None
        mime = str(att.get("mime_type") or ("image/*" if image else ""))
        parts.append({"content_type": _kind_of(mime) if url else "unsupported", "media_url": url})
    return parts


def message_parts(message: dict, *, page_id: str) -> dict | None:
    """What one Meta message becomes here, or ``None`` when there is nothing to store.

    ``from_page`` is true for a reply the Page sent (typed in its inbox, or sent by us earlier):
    that is an outbound agent message, the way an echo is stored. Anything else is the customer.
    """
    mid = message.get("id")
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    sender_id = str(sender.get("id") or "")
    created = parse_time(message.get("created_time"))
    if not isinstance(mid, str) or not mid or not sender_id or created is None:
        return None
    text = message.get("message")
    body = text.strip()[:4000] if isinstance(text, str) and text.strip() else None
    attachments = _attachment_parts(message)
    if body is None and not attachments:
        return None
    parts: list[dict] = []
    if attachments:
        for index, att in enumerate(attachments):
            parts.append(
                {
                    "mid": mid if index == 0 else f"{mid}#{index}",
                    "body": body if index == 0 else None,
                    **att,
                }
            )
    else:
        parts.append({"mid": mid, "body": body, "content_type": "text", "media_url": None})
    return {
        "from_page": sender_id == str(page_id),
        "sender_id": sender_id,
        "sender_name": str(sender.get("name") or "").strip()[:255] or None,
        "created_at": created,
        "parts": parts,
    }


def customer_of(thread: dict, *, page_id: str) -> tuple[str, str | None] | None:
    """The person on the other side of a thread: ``(page-scoped id, name)``."""
    participants = thread.get("participants")
    rows = participants.get("data") if isinstance(participants, dict) else participants
    for person in rows or []:
        if isinstance(person, dict) and str(person.get("id") or "") not in ("", str(page_id)):
            name = str(person.get("name") or "").strip()[:255] or None
            return str(person["id"]), name
    return None


# --------------------------------------------------------------------------- Meta reads ---


def _usage_percent(response: httpx.Response) -> int:
    """The highest call-count percentage Meta reports in ``x-app-usage``/``x-page-usage``."""
    import json

    highest = 0
    for header in ("x-app-usage", "x-page-usage"):
        raw = response.headers.get(header)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, (int, float)):
                    highest = max(highest, int(value))
    return highest


class _ProviderDown(Exception):
    """Meta failed in a way that says "back off" (5xx, throttle). Raised inside the breaker."""


async def _get(http: httpx.AsyncClient, url: str, params: dict, *, tolerate: bool = False):
    """One Graph read, through the Messenger circuit breaker.

    A 5xx or a throttle is raised INSIDE ``breaker.call`` so it counts against the breaker; a
    dead Meta is then left alone instead of being asked for every thread. An open breaker ends the
    run cleanly (``BackfillStopped``), resumable later. A client error is not an outage: a single
    message Meta calls "deleted" returns ``None`` when ``tolerate`` is set, and any other 4xx stops
    the run without touching the breaker.

    The caller sees ``BackfillStopped`` for every reason the run must end, never a raw exception.
    """
    from app.core.circuit_breaker import PROVIDER_MESSENGER, get_breaker
    from app.core.errors import CircuitOpenError

    async def _once() -> tuple[httpx.Response, Any]:
        response = await http.get(url, params=params)
        if response.status_code == 429 or response.status_code >= 500:
            raise _ProviderDown(f"meta_{response.status_code}")
        if _usage_percent(response) >= USAGE_STOP_PERCENT:
            raise _ProviderDown("rate_limited")
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict) and error.get("code") in (4, 17, 32, 613):
            raise _ProviderDown("rate_limited")
        return response, data

    try:
        response, data = await get_breaker(PROVIDER_MESSENGER).call(_once)
    except CircuitOpenError:
        raise BackfillStopped("provider_unavailable") from None
    except _ProviderDown as down:
        raise BackfillStopped(
            "rate_limited" if "rate" in str(down) or "429" in str(down) else str(down)
        ) from None
    except httpx.RequestError as exc:
        raise BackfillStopped(f"network: {type(exc).__name__}") from None
    if response.is_success and isinstance(data, dict):
        return data
    if tolerate:
        return None
    error = data.get("error") if isinstance(data, dict) else None
    message = error.get("message") if isinstance(error, dict) else f"HTTP {response.status_code}"
    raise BackfillStopped(f"meta_error: {str(message)[:120]}")


async def list_threads(
    http: httpx.AsyncClient, *, page_id: str, token: str, after: str | None = None
) -> dict:
    """One page of the Page's Messenger threads, newest first."""
    params = {
        "platform": "messenger",
        "fields": _THREAD_FIELDS,
        "limit": THREAD_PAGE_SIZE,
        "access_token": token,
    }
    if after:
        params["after"] = after
    return await _get(http, f"{_GRAPH}/{page_id}/conversations", params)


async def thread_message_ids(
    http: httpx.AsyncClient, *, thread_id: str, token: str, limit: int
) -> list[str]:
    """The newest ``limit`` message ids of a thread (Meta lists them newest first)."""
    data = await _get(
        http,
        f"{_GRAPH}/{thread_id}",
        {"fields": f"messages.limit({limit}){{id,created_time}}", "access_token": token},
    )
    rows = (data.get("messages") or {}).get("data") or []
    return [str(r["id"]) for r in rows if isinstance(r, dict) and r.get("id")][:limit]


async def read_message(http: httpx.AsyncClient, *, message_id: str, token: str) -> dict | None:
    return await _get(
        http,
        f"{_GRAPH}/{message_id}",
        {"fields": _MESSAGE_FIELDS, "access_token": token},
        tolerate=True,
    )


# --------------------------------------------------------------------------- writing ---


async def _known_ids(session: AsyncSession, tenant_id: uuid.UUID, ids: list[str]) -> set[str]:
    from app.modules.conversations.models import Message

    if not ids:
        return set()
    rows = await session.execute(
        select(Message.channel_message_id).where(
            Message.tenant_id == tenant_id, Message.channel_message_id.in_(ids)
        )
    )
    return {r[0] for r in rows}


async def store_message(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    conversation,
    parsed: dict,
) -> int:
    """Write one parsed message's rows (if new) and move the thread's clocks only forward."""
    from app.modules.conversations.models import Message

    ids = [p["mid"] for p in parsed["parts"]]
    known = await _known_ids(session, tenant_id, ids)
    written = 0
    for part in parsed["parts"]:
        if part["mid"] in known:
            continue
        from_page = parsed["from_page"]
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                channel=conversation.channel,
                direction="outbound" if from_page else "inbound",
                sender_type="agent" if from_page else "customer",
                channel_message_id=part["mid"],
                body=part["body"],
                media_url=part["media_url"],
                media_type=part["content_type"] if part["media_url"] else None,
                content_type=part["content_type"],
                status="sent" if from_page else "received",
                provider_metadata={"source": "messenger_backfill"},
                payload={},
                created_at=parsed["created_at"],
            )
        )
        written += 1
    if not written:
        return 0
    at = parsed["created_at"]
    if conversation.last_message_at is None or at > conversation.last_message_at:
        conversation.last_message_at = at
    if not parsed["from_page"] and (
        conversation.last_customer_message_at is None or at > conversation.last_customer_message_at
    ):
        conversation.last_customer_message_at = at
    return written


async def _conversation_for_customer(
    session: AsyncSession, tenant_id: uuid.UUID, psid: str, name: str | None, result: BackfillResult
):
    """The customer behind a page-scoped id and their open Messenger conversation, made if new.

    A thread that has to be created starts quiet: no unread count and nothing queued, because a
    history import is not a customer waiting for an answer.
    """
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import CustomerIdentity
    from app.modules.customers.service import CustomerService

    existed = (
        await session.execute(
            select(CustomerIdentity.id).where(
                CustomerIdentity.tenant_id == tenant_id,
                CustomerIdentity.channel == CHANNEL,
                CustomerIdentity.external_id == psid,
            )
        )
    ).first()
    customer = await CustomerService.get_or_create_by_identity(
        session, tenant_id, channel=CHANNEL, external_id=psid, name=name
    )
    if existed is None:
        result.customers_created += 1
    conversation = (
        await session.execute(
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.customer_id == customer.id,
                Conversation.channel == CHANNEL,
                Conversation.status != "closed",
            )
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(1)
        )
    ).scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(
            tenant_id=tenant_id, customer_id=customer.id, channel=CHANNEL, unread_count=0
        )
        session.add(conversation)
        await session.flush()
    return conversation


async def run_page(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    page_id: str,
    token: str,
    since: datetime | None = None,
    cursor: str | None = None,
    max_threads: int = DEFAULT_MAX_THREADS,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    threads_done: int = 0,
    http: httpx.AsyncClient | None = None,
    pause: float = 0.2,
) -> BackfillResult:
    """Backfill one page of threads. ``next_cursor`` is set when more remain within the caps.

    ``since`` is the oldest message time to keep (default: now minus ``DEFAULT_DAYS``). Threads are
    newest first, so the first thread last updated before ``since`` ends the run: everything after
    it is older still.
    """
    result = BackfillResult()
    cutoff = since or (datetime.now(UTC) - timedelta(days=DEFAULT_DAYS))
    own = http or httpx.AsyncClient(timeout=20.0)
    try:
        page = await list_threads(own, page_id=page_id, token=token, after=cursor)
        threads = [t for t in page.get("data") or [] if isinstance(t, dict)]
        exhausted = True
        for thread in threads:
            if threads_done + result.threads_seen >= max_threads:
                exhausted = False
                break
            updated = parse_time(thread.get("updated_time"))
            if updated is not None and updated < cutoff:
                result.next_cursor = None
                result.stopped_reason = "window_reached"
                return result
            person = customer_of(thread, page_id=page_id)
            thread_id = thread.get("id")
            if person is None or not isinstance(thread_id, str):
                continue
            result.threads_seen += 1
            ids = await thread_message_ids(
                own, thread_id=thread_id, token=token, limit=max_messages
            )
            known = await _known_ids(session, tenant_id, ids)
            result.messages_known += len(known)
            conversation = None
            # Oldest first, so a thread's clocks are set by the real order of its messages.
            for mid in reversed([i for i in ids if i not in known]):
                raw = await read_message(own, message_id=mid, token=token)
                if raw is None:
                    result.messages_unreadable += 1
                    continue
                parsed = message_parts(raw, page_id=page_id)
                if parsed is None or parsed["created_at"] < cutoff:
                    continue
                if conversation is None:
                    conversation = await _conversation_for_customer(
                        session, tenant_id, person[0], person[1], result
                    )
                result.messages_written += await store_message(
                    session, tenant_id, conversation, parsed
                )
                await asyncio.sleep(pause)
        paging = page.get("paging") if isinstance(page.get("paging"), dict) else {}
        after = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
        if exhausted and after:
            result.next_cursor = str(after)
        elif not exhausted:
            result.stopped_reason = "thread_cap"
        await session.flush()
    except BackfillStopped as stop:
        result.stopped_reason = str(stop)
        result.next_cursor = cursor  # resume from the page that was interrupted
        await session.flush()
    finally:
        if http is None:
            await own.aclose()
    return result
