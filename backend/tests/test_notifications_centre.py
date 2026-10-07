"""NOTIFICATIONS tests — the centre's filters, counts, and mark-read contract.

Two classes again: DB-free guards that the routes and query params exist, and
DB-backed tests for the behaviour, including the 404 contract that the route
used to violate by answering 200 with {"detail": "not found"}.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.security import hash_password
from app.main import create_app
from app.modules.identity.models import User
from app.modules.notifications.router import MarkReadRequest
from app.modules.notifications.service import NotificationService
from app.modules.platform.models import Notification

BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


# ------------------------------------------------------- route surface -----


def test_all_notification_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    expected = {
        "/api/v1/notifications",
        "/api/v1/notifications/unread-count",
        "/api/v1/notifications/summary",
        "/api/v1/notifications/mark-read",
        "/api/v1/notifications/mark-all-read",
        "/api/v1/notifications/{notification_id}/read",
    }
    assert expected <= paths


def test_list_route_exposes_its_filters() -> None:
    """A centre filters by kind and by unread; both must be on the wire."""
    params = create_app().openapi()["paths"]["/api/v1/notifications"]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert {"unread_only", "kind", "limit", "offset"} <= names


def test_mark_read_request_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        MarkReadRequest(ids=[])
    with pytest.raises(PydanticValidationError):
        MarkReadRequest(ids=[uuid.uuid4()] * 101)
    # A single id and a full batch of 100 are both valid.
    MarkReadRequest(ids=[uuid.uuid4()])
    MarkReadRequest(ids=[uuid.uuid4() for _ in range(100)])


# ------------------------------------------------------------- helpers -----


async def _other_user(db: AsyncSession) -> User:
    user = User(
        email=f"other-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name="Other User",
    )
    db.add(user)
    await db.flush()
    return user


async def _notify(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    minutes: int,
    kind: str = "system",
    body: str = "hello",
) -> Notification:
    """Insert a notification with an EXPLICIT created_at.

    `minutes` is required on purpose. Postgres `now()` is the *transaction*
    time, so every row created through the service inside one test transaction
    shares a timestamp — and the list's `id` tiebreaker is a random uuid4, so an
    ordering assertion over those rows is meaningless. A distinct `minutes` is
    the only thing that makes an order assertion mean anything.
    """
    notif = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        kind=kind,
        body=body,
        created_at=_at(minutes),
    )
    db.add(notif)
    await db.flush()
    return notif


# ------------------------------------------------------------- listing -----


async def test_list_is_newest_first(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    for minutes, body in ((10, "first"), (30, "third"), (20, "second")):
        await _notify(db, tenant_id, user_id, body=body, minutes=minutes)

    rows = await NotificationService.list_for_user(db, tenant_id, user_id)
    assert [r.body for r in rows] == ["third", "second", "first"]


async def test_list_filters_by_kind(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    await _notify(db, tenant_id, user_id, kind="sla_breach", body="a", minutes=10)
    await _notify(db, tenant_id, user_id, kind="order_paid", body="b", minutes=20)
    await _notify(db, tenant_id, user_id, kind="order_paid", body="c", minutes=30)

    only_paid = await NotificationService.list_for_user(db, tenant_id, user_id, kind="order_paid")
    assert [r.body for r in only_paid] == ["c", "b"]


async def test_list_filters_unread_only(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    read_one = await _notify(db, tenant_id, user_id, body="read", minutes=10)
    await _notify(db, tenant_id, user_id, body="unread", minutes=20)
    await NotificationService.mark_read(db, tenant_id, user_id, read_one.id)

    unread = await NotificationService.list_for_user(db, tenant_id, user_id, unread_only=True)
    assert [r.body for r in unread] == ["unread"]


async def test_list_never_returns_another_users_notifications(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    other = await _other_user(db)
    await _notify(db, tenant_id, other.id, body="not yours", minutes=10)

    rows = await NotificationService.list_for_user(db, tenant_id, tenant_ctx.user.id)
    assert rows == []


# ------------------------------------------------------------ summary -----


async def test_summary_counts_total_unread_and_by_kind(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    first = await _notify(db, tenant_id, user_id, kind="sla_breach", body="a", minutes=10)
    await _notify(db, tenant_id, user_id, kind="sla_breach", body="b", minutes=20)
    await _notify(db, tenant_id, user_id, kind="order_paid", body="c", minutes=30)
    await NotificationService.mark_read(db, tenant_id, user_id, first.id)

    summary = await NotificationService.summary(db, tenant_id, user_id)

    assert summary["total"] == 3
    assert summary["unread"] == 2
    by_kind = {row["kind"]: row for row in summary["by_kind"]}
    assert by_kind["sla_breach"] == {"kind": "sla_breach", "total": 2, "unread": 1}
    assert by_kind["order_paid"] == {"kind": "order_paid", "total": 1, "unread": 1}


async def test_summary_on_an_empty_inbox_is_zeroed(db: AsyncSession, tenant_ctx):
    summary = await NotificationService.summary(db, tenant_ctx.tenant_id, tenant_ctx.user.id)
    assert summary == {"total": 0, "unread": 0, "by_kind": []}


async def test_summary_ignores_other_users(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    other = await _other_user(db)
    await _notify(db, tenant_id, other.id, body="not yours", minutes=10)

    summary = await NotificationService.summary(db, tenant_id, tenant_ctx.user.id)
    assert summary["total"] == 0


# ---------------------------------------------------------- mark read -----


async def test_mark_read_raises_not_found(db: AsyncSession, tenant_ctx):
    """The route used to answer 200 with {"detail": "not found"}."""
    with pytest.raises(NotFoundError):
        await NotificationService.mark_read(
            db, tenant_ctx.tenant_id, tenant_ctx.user.id, uuid.uuid4()
        )


async def test_mark_read_is_idempotent(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    notif = await _notify(db, tenant_id, user_id, minutes=10)

    first = await NotificationService.mark_read(db, tenant_id, user_id, notif.id)
    stamped = first.read_at
    assert stamped is not None

    # Re-reading must not move the original timestamp.
    second = await NotificationService.mark_read(db, tenant_id, user_id, notif.id)
    assert second.read_at == stamped


async def test_mark_read_cannot_touch_another_users_notification(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    other = await _other_user(db)
    theirs = await _notify(db, tenant_id, other.id, minutes=10)

    with pytest.raises(NotFoundError):
        await NotificationService.mark_read(db, tenant_id, tenant_ctx.user.id, theirs.id)


async def test_mark_many_read_only_touches_the_given_ids(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    a = await _notify(db, tenant_id, user_id, body="a", minutes=10)
    b = await _notify(db, tenant_id, user_id, body="b", minutes=20)
    await _notify(db, tenant_id, user_id, body="c", minutes=30)

    marked = await NotificationService.mark_many_read(db, tenant_id, user_id, [a.id, b.id])
    assert marked == 2

    unread = await NotificationService.list_for_user(db, tenant_id, user_id, unread_only=True)
    assert [r.body for r in unread] == ["c"]


async def test_mark_many_read_is_scoped_to_the_caller(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    other = await _other_user(db)
    theirs = await _notify(db, tenant_id, other.id, minutes=10)

    marked = await NotificationService.mark_many_read(
        db, tenant_id, tenant_ctx.user.id, [theirs.id]
    )
    assert marked == 0

    still_unread = await NotificationService.list_for_user(
        db, tenant_id, other.id, unread_only=True
    )
    assert len(still_unread) == 1


async def test_mark_all_read_reports_the_count_and_is_scoped(db: AsyncSession, tenant_ctx):
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id
    other = await _other_user(db)
    await _notify(db, tenant_id, user_id, body="a", minutes=10)
    await _notify(db, tenant_id, user_id, body="b", minutes=20)
    theirs = await _notify(db, tenant_id, other.id, body="theirs", minutes=30)

    marked = await NotificationService.mark_all_read(db, tenant_id, user_id)
    assert marked == 2

    # The other user's notification must still be unread.
    unread = await NotificationService.list_for_user(db, tenant_id, other.id, unread_only=True)
    assert [r.id for r in unread] == [theirs.id]

    # And a second sweep finds nothing left to do.
    assert await NotificationService.mark_all_read(db, tenant_id, user_id) == 0


# ---------------------------------------------------------- dedup key -----


async def test_create_dedups_on_dedup_key(db: AsyncSession, tenant_ctx):
    """Exercises the service's own create() path (not the _notify helper)."""
    tenant_id, user_id = tenant_ctx.tenant_id, tenant_ctx.user.id

    first = await NotificationService.create(
        db, tenant_id, user_id, kind="sla_breach", body="x", dedup_key="sla:conv-1"
    )
    second = await NotificationService.create(
        db, tenant_id, user_id, kind="sla_breach", body="x again", dedup_key="sla:conv-1"
    )

    assert second.id == first.id
    assert second.body == "x"
    assert await NotificationService.unread_count(db, tenant_id, user_id) == 1


async def test_create_relies_on_the_channel_server_default(db: AsyncSession, tenant_ctx):
    """create() never sets `channel`.

    The model declares server_default="inapp" for it, so SQLAlchemy omits the
    column and Postgres supplies the value. When the database had no default
    this raised NotNullViolationError and no notification could be created at
    all — this pins that the default is really there.
    """
    notif = await NotificationService.create(
        db, tenant_ctx.tenant_id, tenant_ctx.user.id, kind="system", body="hi"
    )
    stored = (
        await db.execute(select(Notification.channel).where(Notification.id == notif.id))
    ).scalar_one()
    assert stored == "inapp"
