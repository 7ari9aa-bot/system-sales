"""Reconciliation: what Meta has that FIHRIST does not, and what FIHRIST has that Meta lost.

A backfill alone is half the job. The walker reads the Page's conversations, but nothing compared
the result to what is already stored, so a gap (a webhook that failed for an hour, a thread started
before the channel was connected) stayed invisible, and a thread Meta no longer lists stayed in the
inbox forever.

This module is that comparison. It is bounded by `meta_linking.backfill_bounds` for the provider, so
a reconciliation run can never walk a Page into a rate limit, and it reports a rate limit or an
outage as an error with its reason rather than as "nothing missing".
"""

from __future__ import annotations

from typing import Any

import httpx

from app.modules.conversations.gateway.messenger_backfill import MessengerBackfill
from app.modules.customers.meta_linking import backfill_bounds, backfill_supported


def _thread_id(conversation: dict[str, Any]) -> str | None:
    """Meta's own thread id for a conversation row, or None when the row has none."""
    value = conversation.get("id")
    return str(value) if value else None


async def reconcile_page(
    http: httpx.AsyncClient,
    *,
    page_id: str,
    token: str,
    local_thread_ids: set[str],
    provider: str = "messenger",
    walker: MessengerBackfill | None = None,
) -> dict[str, Any]:
    """Walk what Meta will give us, then say what is missing on each side.

    ``missing_locally`` is the actionable half: a thread Meta has that FIHRIST never stored. A
    thread FIHRIST has that Meta no longer lists is reported too, but as ``stale_locally`` — Meta
    drops conversations from that listing for its own reasons, so it is not proof of a deletion and
    nothing is removed on the strength of it.
    """
    supported, why = backfill_supported(provider)
    if not supported:
        return {
            "supported": False,
            "reason": why,
            "missing_locally": [],
            "stale_locally": [],
            "error": None,
        }

    bounds = backfill_bounds(provider)
    result = await (walker or MessengerBackfill()).walk(
        http,
        page_id=page_id,
        token=token,
        with_messages=False,
        max_conversations=bounds.max_items,
        max_pages=bounds.max_pages,
    )

    meta_ids = {tid for tid in (_thread_id(c) for c in result.conversations) if tid}
    return {
        "supported": True,
        "reason": None,
        "pages_read": result.pages_read,
        "conversations_seen": len(meta_ids),
        "stopped": result.stopped,
        "error": result.error,
        # Only meaningful when the walk completed; a capped or failed walk cannot prove absence.
        "missing_locally": (
            sorted(meta_ids - local_thread_ids) if result.stopped == "exhausted" else []
        ),
        "stale_locally": sorted(local_thread_ids - meta_ids)
        if result.stopped == "exhausted"
        else [],
        "bounds": {
            "max_pages": bounds.max_pages,
            "max_items": bounds.max_items,
            "max_days": bounds.max_days,
        },
    }
