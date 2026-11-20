"""Deciding what to send next, in what order, and what to do with each outcome.

Pure state machine over plain records (no database, no network, no clock of its own) so the
rules that decide fiscal correctness are testable on their own. The persistent worker feeds it
documents and applies the plan it returns.

Rules, all from the authority's published documentation:

* Receipts are chained per POS by ``previousUUID``; they must reach the authority **in issue
  order**. We therefore send each device's pending receipts oldest first, and never skip one.
* A batch is sent once. Any 2xx is final: an accepted receipt is never resent, and a 422
  duplicate (same payload inside 10 minutes) means "already received", not "failed".
* A *rejected* receipt is corrected by building a NEW receipt (new UUID) that keeps the same
  ``previousUUID`` and sets ``referenceOldUUID`` to the rejected one. Later receipts keep
  pointing at the ORIGINAL rejected uuid (the authority's own worked example), so the chain
  does not need to be rewritten.
* That correction must reach the authority within 96 hours of the receipt's issue time
  ("amendment with reference"). After that only a manual Late Submission Request on the
  taxpayer portal can save it, so the plan flags it instead of retrying forever.
* Throttling / outages are retried with backoff; credentials problems are not retried blindly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

AMENDMENT_WITH_REFERENCE = timedelta(hours=96)
AMENDMENT_WITHOUT_REFERENCE = timedelta(hours=72)

# Retry spacing for transient failures: attempt n waits BACKOFF[min(n, len-1)] seconds.
BACKOFF_SECONDS = (30, 120, 600, 1800, 3600)
MAX_BATCH = 100  # conservative; the authority's hard limit is not published (MaximumSizeExceeded)


class DocState(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    VALID = "valid"
    INVALID = "invalid"  # rejected by the authority, awaiting correction
    FAILED = "failed"  # could not be delivered (network/credentials); safe to retry
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class QueuedDoc:
    """The slice of an ``einvoice_documents`` row the planner needs."""

    id: str
    device_serial: str
    uuid: str
    previous_uuid: str
    issued_at: datetime
    state: DocState
    attempts: int = 0
    next_attempt_at: datetime | None = None
    reference_old_uuid: str = ""  # set when this document is a correction
    # The till's own running number. THE order of the chain: ``previousUUID`` of each receipt names
    # the one before it, and that order is the order they were issued, whatever their printed
    # times say (two receipts a moment apart, or an exchange's two halves, can share a time).
    sequence: int = 0


@dataclass(frozen=True)
class Plan:
    """What to do right now for one device."""

    send: tuple[QueuedDoc, ...] = ()  # one batch, already in chain order
    blocked_by: str | None = None  # why nothing is being sent (observable, never silent)
    expiring: tuple[QueuedDoc, ...] = ()  # rejected docs whose correction window is closing
    expired: tuple[QueuedDoc, ...] = ()  # rejected docs now needing a Late Submission Request


def backoff_for(attempts: int) -> timedelta:
    return timedelta(seconds=BACKOFF_SECONDS[min(max(attempts, 0), len(BACKOFF_SECONDS) - 1)])


def plan_device(
    docs: list[QueuedDoc], *, now: datetime, warn_before: timedelta = timedelta(hours=24)
) -> Plan:
    """Plan the next batch for ONE device from all of its not-yet-final documents."""
    ordered = sorted(docs, key=lambda d: (d.sequence, d.issued_at, d.id))

    expired = tuple(
        d
        for d in ordered
        if d.state is DocState.INVALID and now - d.issued_at > AMENDMENT_WITH_REFERENCE
    )
    expiring = tuple(
        d
        for d in ordered
        if d.state is DocState.INVALID
        and d not in expired
        and AMENDMENT_WITH_REFERENCE - (now - d.issued_at) <= warn_before
    )

    # Only receipts that still need delivery are candidates, in issue order.
    todo = [d for d in ordered if d.state in (DocState.PENDING, DocState.FAILED)]
    if not todo:
        return Plan(expiring=expiring, expired=expired)

    # An un-submitted receipt ahead of the batch whose retry time has not come blocks the line:
    # sending the ones behind it would put receipts on the authority out of chain order.
    head = todo[0]
    if head.next_attempt_at is not None and head.next_attempt_at > now:
        return Plan(
            blocked_by=(
                f"waiting to retry {head.uuid[:12]} until {head.next_attempt_at.isoformat()}"
            ),
            expiring=expiring,
            expired=expired,
        )

    batch: list[QueuedDoc] = []
    for d in todo:
        if len(batch) >= MAX_BATCH:
            break
        if d.next_attempt_at is not None and d.next_attempt_at > now:
            break  # keep strict order: stop at the first one that is not due
        batch.append(d)
    return Plan(send=tuple(batch), expiring=expiring, expired=expired)


@dataclass(frozen=True)
class Outcome:
    """Result for one document after a submission attempt."""

    state: DocState
    next_attempt_at: datetime | None
    attempts: int
    needs_correction: bool = False


def after_transient_failure(doc: QueuedDoc, *, now: datetime, retry_after: float = 0.0) -> Outcome:
    """Network/throttle trouble: stay deliverable and wait (longer than ``Retry-After``)."""
    wait = max(backoff_for(doc.attempts), timedelta(seconds=retry_after + 1))
    return Outcome(DocState.FAILED, now + wait, doc.attempts + 1)


def after_accepted(doc: QueuedDoc) -> Outcome:
    return Outcome(DocState.SUBMITTED, None, doc.attempts + 1)


def after_rejected(doc: QueuedDoc, *, now: datetime) -> Outcome:
    """Rejected by the authority: needs a corrected replacement, not a blind retry."""
    in_time = now - doc.issued_at <= AMENDMENT_WITH_REFERENCE
    return Outcome(DocState.INVALID, None, doc.attempts + 1, needs_correction=in_time)
