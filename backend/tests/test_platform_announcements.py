"""Platform announcements — the merchant-facing read path (fe2026110503).

The owner console composes and targets notices; this file pins the ONLY two
merchant-facing behaviours and the traps around them:

* the route is registered on the platform plane and is membership-gated
  (TenantCtxDep), with no permission code — a banner everyone sees needs none;
* liveness is derived from the clock (``starts_at``/``ends_at``), never from a
  stored status — a future notice and an expired one are both invisible;
* audience semantics are exact: ``NULL`` = every tenant, an explicit list
  without this tenant = hidden, and a MALFORMED audience block (or an empty
  list) = hidden — a targeting bug must never widen into "everyone";
* dismissal is per (announcement, user): one staff member's dismiss leaves
  the banner up for colleagues, a double-dismiss is a no-op, and the banner
  returns for a user who never dismissed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.platform.models import PlatformAnnouncement, PlatformAnnouncementDismissal
from app.modules.platform.router import router as platform_router
from app.modules.platform.services.announcements import active_for_user, dismiss

ROUTE_PATHS = {
    "active": "/platform/announcements/active",
    "dismiss": "/platform/announcements/{announcement_id}/dismiss",
}


# ---------------------------------------------------------------------------
# 1. DB-free: the routes exist on the platform plane.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (ROUTE_PATHS["active"], "GET"),
        (ROUTE_PATHS["dismiss"], "POST"),
    ],
)
def test_the_announcement_routes_are_registered(path: str, method: str) -> None:
    assert any(r.path == path and method in r.methods for r in platform_router.routes), (
        f"{method} {path} is missing — a banner with no data source is a dead component"
    )


def test_the_announcement_routes_are_membership_gated() -> None:
    from tests.test_security_events_read_surface import _permission_codes

    for path, method in ((ROUTE_PATHS["active"], "GET"), (ROUTE_PATHS["dismiss"], "POST")):
        codes = _permission_codes(platform_router.routes, path, method)
        assert codes == set(), (
            f"{method} {path} must be plain TenantCtxDep (no permission code) — got {codes}"
        )


# ---------------------------------------------------------------------------
# 2. DB-backed: liveness, audience, dismissal.
# ---------------------------------------------------------------------------


async def _make_announcement(
    db,
    *,
    kind: str = "info",
    title: str = "Deployment tonight",
    body: str = "The platform updates at 22:00.",
    audience: dict | None = None,
    is_active: bool = True,
    starts_delta: timedelta | None = None,
    ends_delta: timedelta | None = None,
) -> PlatformAnnouncement:
    now = datetime.now(UTC)
    row = PlatformAnnouncement(
        kind=kind,
        title=title,
        body=body,
        audience=audience,
        is_active=is_active,
        starts_at=now + starts_delta if starts_delta is not None else now - timedelta(minutes=5),
        ends_at=now + ends_delta if ends_delta is not None else None,
    )
    db.add(row)
    await db.flush()
    return row


async def test_live_announcement_is_returned_for_the_tenant(db, tenant_ctx) -> None:
    row = await _make_announcement(db)

    found = await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id)

    assert found is not None
    assert found.id == row.id


async def test_null_audience_covers_every_tenant(db, tenant_ctx) -> None:
    await _make_announcement(db, audience=None)

    found = await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id)

    assert found is not None


async def test_targeted_audience_excludes_other_tenants(db, tenant_ctx) -> None:
    other_id = uuid.uuid4()
    await _make_announcement(db, audience={"tenant_ids": [str(other_id)]})

    found = await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id)

    assert found is None, "a tenant not on the list must not see a targeted notice"


async def test_malformed_or_empty_audience_never_widens_to_everyone(db, tenant_ctx) -> None:
    await _make_announcement(db, audience={"tenant_ids": []})
    assert await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id) is None

    await _make_announcement(db, audience={"something": "else"})
    assert await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id) is None


async def test_future_and_ended_and_inactive_are_invisible(db, tenant_ctx) -> None:
    future = await _make_announcement(db, starts_delta=timedelta(hours=1))
    ended = await _make_announcement(db, ends_delta=timedelta(minutes=-1))
    inactive = await _make_announcement(db, is_active=False)

    for row in (future, ended, inactive):
        assert await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id) is None, (
            f"announcement {row.id} must not be live"
        )


async def test_dismissal_hides_for_that_user_only_and_is_idempotent(db, tenant_ctx) -> None:
    row = await _make_announcement(db)
    colleague_id = uuid.uuid4()

    first = await dismiss(db, row.id, tenant_ctx.user.id)
    again = await dismiss(db, row.id, tenant_ctx.user.id)

    assert first is True
    assert again is False, "a double-dismiss must be a no-op, not a second row"

    mine = await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id)
    theirs = await active_for_user(db, tenant_ctx.tenant_id, colleague_id)
    assert mine is None, "a dismissed banner must stay gone for the dismissing user"
    assert theirs is not None, "a colleague who never dismissed must still see it"


async def test_a_non_dismissible_announcement_refuses_the_tombstone(db, tenant_ctx) -> None:
    row = await _make_announcement(db)
    row.dismissible = False
    await db.flush()

    dismissed = await dismiss(db, row.id, tenant_ctx.user.id)

    assert dismissed is False, "a notice marked non-dismissable must not vanish"
    assert await active_for_user(db, tenant_ctx.tenant_id, tenant_ctx.user.id) is not None


async def test_dismissal_of_a_nonexistent_announcement_is_harmless(db, tenant_ctx) -> None:
    dismissed = await dismiss(db, uuid.uuid4(), tenant_ctx.user.id)
    assert dismissed is False, "an unknown announcement id must be a no-op, not an FK error"

    remaining = (await db.execute(select(PlatformAnnouncementDismissal))).scalars().all()
    assert remaining == []  # no orphan tombstone rows


# ---------------------------------------------------------------------------
# 3. Wire contract: the endpoint returns the resolved shape or an honest null.
# ---------------------------------------------------------------------------


def _client(db, tenant_id: uuid.UUID, user_id: uuid.UUID):
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=user_id, tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_active_endpoint_returns_null_when_quiet(db, tenant_ctx) -> None:
    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id) as client:
        resp = await client.get("/api/v1/platform/announcements/active")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"announcement": None}


async def test_active_endpoint_and_dismiss_round_trip(db, tenant_ctx) -> None:
    row = await _make_announcement(db)

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id) as client:
        live = await client.get("/api/v1/platform/announcements/active")
        assert live.status_code == 200, live.text
        body = live.json()["announcement"]
        assert body["title"] == "Deployment tonight"
        assert body["dismissible"] is True

        gone = await client.post(f"/api/v1/platform/announcements/{row.id}/dismiss")
        assert gone.status_code == 200

        after = await client.get("/api/v1/platform/announcements/active")

    assert after.json() == {"announcement": None}
