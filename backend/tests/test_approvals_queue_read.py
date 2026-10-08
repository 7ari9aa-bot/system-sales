"""§135 — the approvals QUEUE must tell the truth about its own completeness.

The decide half of this surface is covered elsewhere (binding, gate, and the
Playwright spec). What nothing pinned is the read half, and two things about it
are load-bearing for the screen:

* The route is bounded. ``list_for_tenant`` has always carried a default
  ``limit``, so a reviewer handed exactly 100 pending rows cannot tell 100 from
  1000 — and §135's promise is that this queue is the set of decisions owed.
  The page is now fetched one row deep and cut, and the route says
  ``truncated: true`` when it cut, so a bounded read never presents itself as a
  complete one.
* The gates the screen's comments assert are the gates the routes actually
  declare: reading the queue is tenant-authenticated only, deciding is
  ``ai:approve``. The screen does NOT pre-check permission client-side (it has
  no permission model to consult) precisely because the server owns this, so if
  either gate moved the frontend's stated reasoning would be false. That is
  what the DB-free cases below hold in place.

The truncation cases need ``DATABASE_URL_APP_ADMIN`` and skip locally; CI is
where their verdict is published.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.ai.approvals import APPROVALS_PAGE_SIZE, ApprovalService
from app.modules.ai.models import ApprovalRequest
from app.modules.ai.router import router as ai_router
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

LIST_PATH = "/api/v1/ai/approvals"
ACTION = "create_order"


def _permission_codes(routes, path: str, method: str) -> set[str]:
    """RBAC codes a route declares, found by walking its dependency tree."""
    for route in routes:
        if route.path == path and method in route.methods:
            codes: set[str] = set()
            stack = list(route.dependant.dependencies)
            while stack:
                dependant = stack.pop()
                code = getattr(dependant.call, "code", None)
                if code:
                    codes.add(code)
                stack.extend(dependant.dependencies)
            return codes
    raise AssertionError(f"{method} {path} is not routed")


# ---------------------------------------------------------------------------
# 1. DB-free: the gates the approvals screen reasons about, as declared.
# ---------------------------------------------------------------------------


def test_reading_the_queue_needs_only_a_tenant_context() -> None:
    assert _permission_codes(ai_router.routes, "/ai/approvals", "GET") == set(), (
        "the queue is how a reviewer finds out what is owed; gating the read "
        "would hide pending HIGH-risk actions from the people who must decide them"
    )


def test_deciding_an_approval_is_gated_by_ai_approve() -> None:
    """The gate `pages/AI.jsx` reasons about, pinned where it is declared.

    The screen deliberately does not pre-check permission client-side — it has
    no permission model to consult and renders the server's 403 sentence into
    `approvalError` instead. That reasoning is only honest while this is the
    gate the route carries, so the gate is read off the route and not off a
    comment: `settings:write` used to be the answer, and the route moved to
    `ai:approve` without anyone noticing because a bespoke closure declares no
    `code` for this walk to find.
    """
    codes = _permission_codes(ai_router.routes, "/ai/approvals/{approval_id}/decide", "POST")
    assert codes == {"ai:approve"}, (
        f"decide is gated by {codes or 'nothing'} — the screen shows the server's "
        "refusal verbatim, so a gate this walk cannot see is a gate nobody can pin"
    )


# ---------------------------------------------------------------------------
# harness for the DB-driven half (CI; skipped without a database)
# ---------------------------------------------------------------------------


def _client(db: AsyncSession, tenant_ctx) -> AsyncClient:
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes=set(),  # the list route consults no code
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _pending(db: AsyncSession, tenant_id: uuid.UUID, *, n: int, action: str) -> None:
    """`n` PENDING rows for one action, as the gate leaves them."""
    for _ in range(n):
        db.add(
            ApprovalRequest(
                tenant_id=tenant_id,
                requested_by="ai",
                entity_type="order",
                entity_id=uuid.uuid4().hex[:16],
                action=action,
                risk_level="HIGH",
                payload={"arguments": {"variant_id": uuid.uuid4().hex}},
                status="PENDING",
            )
        )
    await db.flush()


async def test_the_route_says_when_the_queue_is_longer_than_the_page(
    db: AsyncSession, tenant_ctx
) -> None:
    await _pending(db, tenant_ctx.tenant_id, n=3, action=ACTION)

    async with _client(db, tenant_ctx) as client:
        resp = await client.get(LIST_PATH, params={"status": "PENDING"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3
    assert body["truncated"] is False, "a queue that fits the page must not claim otherwise"


async def test_a_full_page_reports_that_more_decisions_are_waiting(
    db: AsyncSession, tenant_ctx
) -> None:
    """The case that matters: page + 1 rows exist, so the screen must say "more"."""
    await _pending(db, tenant_ctx.tenant_id, n=APPROVALS_PAGE_SIZE + 1, action=ACTION)

    async with _client(db, tenant_ctx) as client:
        resp = await client.get(LIST_PATH, params={"status": "PENDING"})

    body = resp.json()
    assert len(body["items"]) == APPROVALS_PAGE_SIZE
    assert body["truncated"] is True, (
        "the extra row was fetched and then silently dropped — a reviewer sees "
        f"{APPROVALS_PAGE_SIZE} decisions owed and cannot tell that more exist"
    )


async def test_a_queue_exactly_one_page_long_is_not_reported_as_truncated(
    db: AsyncSession, tenant_ctx
) -> None:
    """The off-by-one boundary of a fetch that deliberately reads one row deep."""
    await _pending(db, tenant_ctx.tenant_id, n=APPROVALS_PAGE_SIZE, action=ACTION)

    rows, truncated = await ApprovalService.list_for_tenant(
        db, tenant_ctx.tenant_id, status="PENDING"
    )
    assert len(rows) == APPROVALS_PAGE_SIZE
    assert truncated is False, (
        "the probe row must be used for the answer and never returned as content"
    )
