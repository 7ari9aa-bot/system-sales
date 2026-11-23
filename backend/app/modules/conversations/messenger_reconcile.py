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


def _thread_id(conversation: dict[str, Any]) -> str | None:
    """Meta's own thread id for a conversation row, or None when the row has none."""
    value = conversation.get("id")
    return str(value) if value else None


def _participant_ids(conversation: dict[str, Any], *, page_id: str) -> set[str]:
    """The people in a thread: ``participants.data[].id`` without the Page itself.

    Meta's conversation ``id`` is a THREAD id (``t_...``). FIHRIST stores the PERSON (the PSID) as
    the customer identity, so a thread id can never be compared with it: every thread would look
    missing and every customer stale. The participants are the PSIDs, so those are compared.
    """
    participants = conversation.get("participants")
    rows = participants.get("data") if isinstance(participants, dict) else None
    return {
        str(row["id"])
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and row.get("id") and str(row["id"]) != str(page_id)
    }


async def reconcile_page(
    http: httpx.AsyncClient,
    *,
    page_id: str,
    token: str,
    local_person_ids: set[str],
    provider: str = "messenger",
    walker: MessengerBackfill | None = None,
) -> dict[str, Any]:
    """Walk what Meta will give us, then say what is missing on each side.

    Both sides are PEOPLE (the PSID a customer identity stores), never thread ids.
    ``missing_locally`` is the actionable half: a person Meta lists a conversation with that FIHRIST
    never stored. A person FIHRIST has that Meta no longer lists is reported too, but as
    ``stale_locally``: Meta drops conversations from that listing for its own reasons, so it is not
    proof of a deletion and nothing is removed on the strength of it.

    This is a limited-history comparison: it reads at most the provider's bounds of recent
    conversations, so it can find a gap but never proves the whole history is in sync.
    """
    from app.modules.customers.meta_linking import backfill_bounds, backfill_supported

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

    meta_ids: set[str] = set()
    for conversation in result.conversations:
        meta_ids |= _participant_ids(conversation, page_id=page_id)
    return {
        "supported": True,
        "reason": None,
        "pages_read": result.pages_read,
        "conversations_seen": len(result.conversations),
        "people_seen": len(meta_ids),
        "limited_history": True,
        "stopped": result.stopped,
        "error": result.error,
        # Only meaningful when the walk completed; a capped or failed walk cannot prove absence.
        "missing_locally": (
            sorted(meta_ids - local_person_ids) if result.stopped == "exhausted" else []
        ),
        "stale_locally": sorted(local_person_ids - meta_ids)
        if result.stopped == "exhausted"
        else [],
        "bounds": {
            "max_pages": bounds.max_pages,
            "max_items": bounds.max_items,
            "max_days": bounds.max_days,
        },
    }
