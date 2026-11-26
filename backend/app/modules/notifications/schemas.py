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

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ChannelPreference(BaseModel):
    """One delivery channel as the person's screen shows it.

    ``available`` is about THIS deployment, not about the person: a channel with no
    configured provider is reported as unavailable rather than offered as a switch
    that changes nothing. ``locked`` marks in-app, which is always on — the bell row
    is the record of what happened, so it is not a preference.
    """

    channel: str
    label_key: str
    enabled: bool
    available: bool
    locked: bool = False


class QuietHours(BaseModel):
    """The person's quiet window, as ``HH:MM`` in their own clock, or off."""

    start: str | None = None
    end: str | None = None
    #: Whether the window is active at this moment, computed in the person's zone.
    active_now: bool = False


class NotificationPreferencesOut(BaseModel):
    """Everything the personal-notifications screen needs in one answer."""

    channels: list[ChannelPreference]
    quiet_hours: QuietHours
    #: The zone the window is read in: the person's own, else the workspace's.
    timezone: str
    #: The workspace's own switches, so the screen can say why a channel is silent.
    workspace: dict[str, bool]


class NotificationPreferencesUpdate(BaseModel):
    """A partial rewrite of the person's own notification settings.

    ``None`` leaves a value alone. On the quiet window, an empty string on BOTH ends
    clears it — a window needs two ends, and the service refuses a half of one.
    """

    email_enabled: bool | None = None
    push_enabled: bool | None = None
    quiet_start: str | None = Field(default=None, max_length=5)
    quiet_end: str | None = Field(default=None, max_length=5)

    @model_validator(mode="after")
    def _something_to_change(self) -> NotificationPreferencesUpdate:
        if all(
            value is None
            for value in (
                self.email_enabled,
                self.push_enabled,
                self.quiet_start,
                self.quiet_end,
            )
        ):
            raise ValueError("nothing to update")
        return self
