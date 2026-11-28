"""What the merchant needs to see about their e-receipts, as plain functions.

A receipt the tax authority refused can be replaced by a corrected one, but only inside a window
(96 hours, 72 for a return with no reference receipt). After that it takes a manual request on
the taxpayer portal. This module turns a stored receipt into one of a few levels so the screen
can show the ones running out of time first. The window itself is the sender's
(``correction_window``), so the screen and the sender can never disagree about a deadline.

Pure: no session, no clock of its own (the caller passes ``now``), so it is tested without a
database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.applications.apparel.modules.einvoice.providers.eta.sender import (
    AMENDMENT_WITH_REFERENCE,
    AMENDMENT_WITHOUT_REFERENCE,
)

ACCEPTED = frozenset({"reported", "cleared"})
WAITING = frozenset({"submitted", "signed", "draft"})

# ok       nothing for the merchant to do
# retrying delivery trouble; the sender retries on its own, the merchant need not act
# fix      refused, still inside the correction window
# urgent   refused, and the window closes soon (the merchant's own warning threshold)
# expired  refused and past the window: only a Late Submission Request on the portal can save it
LEVELS = ("ok", "retrying", "fix", "urgent", "expired")


@dataclass(frozen=True, slots=True)
class Attention:
    level: str
    hours_left: float | None = None


def _window(doc: Any) -> timedelta:
    # Same rule as the sender's ``correction_window``, read off the stored document.
    if doc.document_type == "return_without_reference":
        return AMENDMENT_WITHOUT_REFERENCE
    return AMENDMENT_WITH_REFERENCE


def attention_of(doc: Any, *, now: datetime, warn_hours: int) -> Attention:
    """How much this receipt needs the merchant, and for a refused one, how long they have."""
    if doc.status == "failed":
        return Attention("retrying")
    if doc.status != "rejected":
        return Attention("ok")
    left = _window(doc) - (now - doc.issued_at)
    if left < timedelta(0):
        return Attention("expired", 0)
    hours = left.total_seconds() / 3600
    if left <= timedelta(hours=warn_hours):
        return Attention("urgent", hours)
    return Attention("fix", hours)


def summarize_documents(docs: list[Any], *, now: datetime, warn_hours: int) -> dict[str, int]:
    """The counters at the top of the screen."""
    out = {
        "total": 0,
        "accepted": 0,
        "waiting": 0,
        "retrying": 0,
        "rejected": 0,
        "fix_now": 0,
        "urgent": 0,
        "expired": 0,
        "needs_attention": 0,
    }
    for doc in docs:
        out["total"] += 1
        if doc.status in ACCEPTED:
            out["accepted"] += 1
        elif doc.status in WAITING:
            out["waiting"] += 1
        a = attention_of(doc, now=now, warn_hours=warn_hours)
        if a.level == "retrying":
            out["retrying"] += 1
        elif doc.status == "rejected":
            out["rejected"] += 1
            if a.level in ("fix", "urgent"):
                out["fix_now"] += 1
            if a.level == "urgent":
                out["urgent"] += 1
            if a.level == "expired":
                out["expired"] += 1
            out["needs_attention"] += 1
    return out
