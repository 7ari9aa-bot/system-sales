"""NOTIFICATIONS request/response contracts.

Why this file exists (register P7's response half)
--------------------------------------------------
The centre's surface was half-typed: the list and the single-read route returned
a model, but the counters — the bell's badge, the bulk mark-read acknowledgement
and the two aggregate views — answered with ``dict`` / ``dict[str, int]`` /
``-> dict``. On the wire an anonymous object is not a contract: a generated
client has nothing to hold, and a handler that renames ``marked`` to ``count``
(or the other way round, which is why both spellings exist here) is caught by
nobody until a badge stops moving. ``tests/test_notifications_contracts.py``
pins every route to a named schema, and pins the two counter names separately.

Money
-----
Nothing on this surface carries an amount: the counts and the digest groups are
integers, the timestamps are datetimes. The stringification rule (``str(Decimal)``
across the wire) is untouched here and lives with ORDERS/PAYMENTS.

Pagination bounds
-----------------
``PAGE_MAX``/``OFFSET_MAX`` live in ONE place and both halves read from it: the
route turns them into ``Query(ge=…, le=…)`` (so ``?limit=-1`` is a 422, never a
``LIMIT -1``) and the service re-checks them (so an in-process caller — the
bell's own aggregates, a future worker — cannot walk past a cap that only exists
in the route, which is exactly how a query string became a 500).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The widest page ``GET /notifications`` will take, at the route AND in the
#: service. A cap that lives only in the route can be walked past in-process.
PAGE_MAX = 200
#: An offset past this is not a page a human scrolls to; it is a full scan, and
#: the inbox is capped by retention long before here. Paging beyond it wants a
#: cursor, not a bigger number.
OFFSET_MAX = 10_000
#: The largest bulk mark-read sweep a client may ask for in one request. Kept
#: separate from ``PAGE_MAX`` on purpose: the page size is what the bell renders,
#: this is what one write may stamp, and ``test_mark_read_request_bounds`` pins
#: 100 (a 101-id body is a refusal, not a truncation).
MARK_READ_MAX = 100


class NotificationOut(BaseModel):
    """One inbox row, as the centre renders it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str | None
    body: str
    action_url: str | None
    payload: dict[str, Any]
    read_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: Any) -> NotificationOut:
        """Build from the ORM row, keeping ``payload`` an object when unset.

        ``payload`` is ``JSONB`` with a server default, but a row staged in the
        same uncommitted transaction has no server value yet, and a client
        reading ``payload.foo`` should get an empty object, not a null.
        """
        return cls(
            id=row.id,
            kind=row.kind,
            title=row.title,
            body=row.body,
            action_url=row.action_url,
            payload=row.payload or {},
            read_at=row.read_at,
            created_at=row.created_at,
        )


class MarkReadRequest(BaseModel):
    """The ids to stamp. Non-empty and bounded: an empty body is a typo."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=MARK_READ_MAX)


class UnreadCount(BaseModel):
    """The bell's badge."""

    count: int


class MarkReadResult(BaseModel):
    """How many rows the bulk sweep actually stamped — 0 is a valid answer."""

    marked: int


class KindTotals(BaseModel):
    """One filter tab: how many rows of this kind, how many still unread."""

    kind: str
    total: int
    unread: int


class NotificationSummary(BaseModel):
    """Totals the centre labels its filters with."""

    total: int
    unread: int
    by_kind: list[KindTotals]


class DigestGroup(BaseModel):
    kind: str
    count: int
    latest_at: str | None


class NotificationDigest(BaseModel):
    """§166: the bell's collapsed view — "5 new orders, 2 SLA breaches"."""

    total_unread: int
    groups: list[DigestGroup]
