"""W4-T8 — an operator surface over the M12 quarantine.

The migration (``d5a1c7e94b02``) marked the rows it could not safely fix inside
``customers.extra -> data_quality -> m12_contact_backfill``, and
``GET /customers/contact-data-issues`` lists them. What never existed is the
other half of a work queue: nothing could CLEAR a mark, so every row the
backfill handed to a human stayed in the queue forever, marked, even after the
human decided.

This file pins the resolve side, and its refusals:

* ``phone_legacy_default_country`` (a ``+9640…`` fabrication of an Egyptian
  number) resolves two ways — ``confirm_genuine`` (the number really is what
  the column says; the mark was about the writer, not the person) or
  ``correct`` (the operator states the real phone; it is canonicalized with
  the same strict rule every human write uses, and refused if a live customer
  already holds it).
* ``phone_canonical_collision`` resolves ONLY to ``confirm_distinct`` —
  "these are two different people". Merging two customers retargets orders,
  conversations and ledgers and tombstones one row; ``IdentityMergeService``
  is deliberately gated behind a human decision and this endpoint refuses to
  reach around it (``POST /customers/merge`` already exists for that).
* A row whose issue is not open answers 409 with the server's REAL open
  issues — it never reports success on a mark that is not there.
* Every mutation writes one audit row through ``app.core.audit``.

The route-shape, permission-gate and TENANCY-SHAPE cases are DB-free: the
resolver is pointed at a stub session that only hides a foreign row from a
SELECT carrying ``customers.tenant_id``, so the scoping rule is pinned even
where no database is reachable. Everything that reads or clears a real mark
needs ``DATABASE_URL_APP_ADMIN`` and skips locally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import TENANT_GUC, bind_tenant
from app.main import create_app
from app.modules.customers.models import Customer
from app.modules.customers.router import router as customers_router
from app.modules.customers.service import CustomerService
from app.modules.errors import NotFoundError
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant

EGYPT = "+201001234567"
FABRICATED = "+9640201001234567"
LEGACY_ISSUE = "phone_legacy_default_country"
COLLISION_ISSUE = "phone_canonical_collision"

RESOLVE_PATH_TPL = "/api/v1/customers/{}/contact-issue/resolve"

_REVIEW_MARK: dict = {
    "phone_status": "needs_review",
    "legacy_raw": "0201001234567",
    "suspected_phone": EGYPT,
}
_COLLISION_MARK: dict = {
    "phone_collision": {"canonical": EGYPT, "peer_customer_ids": [str(uuid.uuid4())]},
}


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
# 1. DB-free: the route exists and is gated at the ROUTE, not in the body.
# ---------------------------------------------------------------------------


def test_the_resolve_route_is_registered_on_the_customers_router() -> None:
    assert any(
        r.path == "/customers/{customer_id}/contact-issue/resolve" and "POST" in r.methods
        for r in customers_router.routes
    ), "the quarantine queue needs its resolve half routed"


def test_resolving_a_contact_issue_is_gated_by_customers_write() -> None:
    codes = _permission_codes(
        customers_router.routes, "/customers/{customer_id}/contact-issue/resolve", "POST"
    )
    assert codes == {"customers:write"}, (
        "the queue is a work surface for someone who can act on it — the same "
        "gate the list uses; no new permission strings"
    )


def _permission_only_app(permissions: set[str]):
    """The real app with ONLY the auth context swapped; nothing touches the DB
    because a refused caller never reaches a handler."""
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=None,  # never used: both calls under test are refused first
            user=AuthedUser(id=uuid.uuid4(), tenant_id=None, role_code="staff"),
            tenant_id=uuid.uuid4(),
            role_code="staff",
            permission_codes=set(permissions),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def test_a_caller_without_write_cannot_list_or_resolve() -> None:
    body = {"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"}
    async with AsyncClient(
        transport=ASGITransport(app=_permission_only_app({"customers:read"})),
        base_url="http://test",
    ) as client:
        listed = await client.get("/api/v1/customers/contact-data-issues")
        resolved = await client.post(RESOLVE_PATH_TPL.format(uuid.uuid4()), json=body)

    assert listed.status_code == 403, listed.text
    assert resolved.status_code == 403, (
        f"expected the permission gate, got {resolved.status_code} — "
        "a route that 404s is not a gated route"
    )


# ---------------------------------------------------------------------------
# harness for the DB-driven half (CI; skipped without a database)
# ---------------------------------------------------------------------------


async def _marked(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    phone: str | None = FABRICATED,
    name: str = "Quarantined",
    flag: dict,
) -> uuid.UUID:
    """Insert a row carrying a backfill mark, exactly as the migration leaves it."""
    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        phone=phone,
        extra={"data_quality": {"m12_contact_backfill": {**flag, "revision": "d5a1c7e94b02"}}},
    )
    db.add(customer)
    await db.flush()
    return customer.id


def _client(db: AsyncSession, tenant_ctx, permissions: set[str]) -> AsyncClient:
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes=set(permissions),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


WRITE = {"customers:write"}
PII = {"customers:write", "pii:read"}


async def _flag(db: AsyncSession, customer_id: uuid.UUID) -> dict:
    """The mark the DATABASE holds for that row right now.

    A plain column SELECT re-reads ``customers.extra`` from the connection, and
    the endpoint flushes before it answers, so the DB is already the truth.
    ``db.expire_all()`` deliberately does NOT go here: the identity map also
    holds the fixture's own ORM ``User`` (``tenant_ctx.user``), so a whole-map
    expiry turns the next ``tenant_ctx.user.id`` read into a synchronous reload
    of that expired ``users.id`` column — which async SQLAlchemy cannot do
    outside a greenlet, and the test died with ``MissingGreenlet`` on a line of
    its own rather than on the product path. ``Customer`` and ``User`` rows are
    separate objects; nothing here needs the session to forget them.

    The read is also tenant-bound: FORCE RLS filters ``customers`` by the GUC,
    so under a caller's binding a foreign row's ``extra`` comes back NULL —
    invisibility, not an emptied mark. A test that means to inspect another
    tenant's row reads it inside ``_seen_as(owner)``.
    """
    extra = await db.scalar(select(Customer.extra).where(Customer.id == customer_id))
    return ((extra or {}).get("data_quality") or {}).get("m12_contact_backfill") or {}


async def _audit_rows(db: AsyncSession, customer_id: uuid.UUID) -> list:
    return (
        await db.execute(
            text(
                "SELECT action, resource_type, actor_user_id FROM audit_logs "
                "WHERE resource_id = :rid"
            ),
            {"rid": str(customer_id)},
        )
    ).all()


@asynccontextmanager
async def _seen_as(db: AsyncSession, tenant_id: uuid.UUID) -> AsyncIterator[uuid.UUID]:
    """Read the block under TENANT_ID's RLS binding, then restore the previous one.

    The only honest way to look at another tenant's row: FORCE RLS filters
    ``customers`` (and ``audit_logs``) on the ``app.tenant_id`` GUC, so a query
    under any other binding answers ``NULL``/``no rows`` for it.
    """
    previous = await db.scalar(text(f"SELECT current_setting('{TENANT_GUC}', true)"))
    await bind_tenant(db, tenant_id)
    try:
        yield tenant_id
    finally:
        if previous is not None:
            await bind_tenant(db, uuid.UUID(previous))


# ---------------------------------------------------------------------------
# 2. confirm_genuine clears EXACTLY the mark it claims (and nothing else)
# ---------------------------------------------------------------------------


async def test_confirm_genuine_clears_only_the_review_keys_and_audits(
    db: AsyncSession, tenant_ctx
) -> None:
    row_id = await _marked(
        db,
        tenant_ctx.tenant_id,
        flag={**_REVIEW_MARK, **_COLLISION_MARK, "phone_from": "01001234567"},
    )
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"},
        )
        assert response.status_code == 200, response.text

    flag = await _flag(db, row_id)
    assert set(flag) == {"phone_collision", "phone_from", "revision"}, (
        "the collision, the provenance of a rewrite, and the revision are NOT "
        "this resolution's to clear"
    )
    assert await db.scalar(select(Customer.phone).where(Customer.id == row_id)) == FABRICATED
    body = response.json()
    assert body["issues"] == [COLLISION_ISSUE], "the surviving issue stays listed"
    assert await _audit_rows(db, row_id) == [
        ("customer.contact_issue_resolved", "customer", tenant_ctx.user.id)
    ]


# ---------------------------------------------------------------------------
# 3. correct — the operator states the real phone
# ---------------------------------------------------------------------------


async def test_correct_stores_the_canonical_phone_and_clears_the_review_mark(
    db: AsyncSession, tenant_ctx
) -> None:
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK))
    async with _client(db, tenant_ctx, PII) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": LEGACY_ISSUE, "resolution": "correct", "phone": "0100 123 4567"},
        )
        assert response.status_code == 200, response.text

    assert await db.scalar(select(Customer.phone).where(Customer.id == row_id)) == EGYPT
    assert set(await _flag(db, row_id)) == {"revision"}
    body = response.json()
    assert body["issues"] == []
    assert body["phone"] == EGYPT, "with pii:read the response shows the new real value"
    assert await _audit_rows(db, row_id)


async def test_correct_refuses_a_phone_another_live_customer_already_holds(
    db: AsyncSession, tenant_ctx
) -> None:
    holder = Customer(id=uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, name="Holder", phone=EGYPT)
    db.add(holder)
    await db.flush()
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK))

    async with _client(db, tenant_ctx, PII) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": LEGACY_ISSUE, "resolution": "correct", "phone": "01001234567"},
        )

    assert response.status_code == 409, response.text
    assert await db.scalar(select(Customer.phone).where(Customer.id == row_id)) == FABRICATED
    assert "phone_status" in await _flag(db, row_id), "a refusal clears nothing"


async def test_correct_canonicalizes_with_the_same_strict_rule_as_every_write(
    db: AsyncSession, tenant_ctx
) -> None:
    """An unparseable value must 400 the request, never reach the uniqueness key."""
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK))
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": LEGACY_ISSUE, "resolution": "correct", "phone": "call me maybe"},
        )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_correct_without_a_phone_is_refused(db: AsyncSession, tenant_ctx) -> None:
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK))
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": LEGACY_ISSUE, "resolution": "correct"},
        )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# 4. collisions — and the merge this surface REFUSES to automate
# ---------------------------------------------------------------------------


async def test_confirm_distinct_clears_only_the_collision_mark(
    db: AsyncSession, tenant_ctx
) -> None:
    row_id = await _marked(db, tenant_ctx.tenant_id, flag={**_REVIEW_MARK, **_COLLISION_MARK})
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": COLLISION_ISSUE, "resolution": "confirm_distinct"},
        )
        assert response.status_code == 200, response.text

    assert set(await _flag(db, row_id)) == {*_REVIEW_MARK, "revision"}
    assert response.json()["issues"] == [LEGACY_ISSUE]


async def test_merging_two_customers_is_not_an_offered_resolution(
    db: AsyncSession, tenant_ctx
) -> None:
    """The refusal is the product decision: a merge retargets orders,
    conversations and ledgers and tombstones a row. That is POST
    /customers/merge's human-gated job, not a mark-clearer's."""
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_COLLISION_MARK))
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": COLLISION_ISSUE, "resolution": "merge"},
        )

    assert response.status_code == 400, response.text
    assert "/customers/merge" in response.json()["error"]["message"], (
        "the refusal must point at the path that actually merges"
    )
    assert "phone_collision" in await _flag(db, row_id)


# ---------------------------------------------------------------------------
# 5. refusals that tell the truth: 404 for no row, 409 with the REAL state
# ---------------------------------------------------------------------------


async def test_an_unknown_customer_is_a_404_shaped_refusal(db: AsyncSession, tenant_ctx) -> None:
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(uuid.uuid4()),
            json={"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"},
        )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_resolving_a_closed_issue_answers_with_the_servers_real_state(
    db: AsyncSession, tenant_ctx
) -> None:
    """No lie, in either direction: the row has a collision, not a review mark,
    and the refusal says so."""
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_COLLISION_MARK))
    async with _client(db, tenant_ctx, WRITE) as client:
        first = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={
                "issue": COLLISION_ISSUE,
                "resolution": "confirm_distinct",
            },
        )
        assert first.status_code == 200, first.text
        stale = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": COLLISION_ISSUE, "resolution": "confirm_distinct"},
        )
        wrong = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"},
        )

    assert stale.status_code == 409, stale.text
    assert wrong.status_code == 409, wrong.text
    # The message carries the server's actual open issues — here, none left.
    assert "no open" in stale.json()["error"]["message"]
    assert set(await _flag(db, row_id)) == {"revision"}


async def test_a_row_that_was_never_marked_refuses_resolution(db: AsyncSession, tenant_ctx) -> None:
    plain = Customer(id=uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, name="Clean", phone=EGYPT)
    db.add(plain)
    await db.flush()
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(plain.id),
            json={"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"},
        )
    assert response.status_code == 409, response.text


async def test_an_unknown_issue_name_is_a_400(db: AsyncSession, tenant_ctx) -> None:
    row_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK))
    async with _client(db, tenant_ctx, WRITE) as client:
        response = await client.post(
            RESOLVE_PATH_TPL.format(row_id),
            json={"issue": "smells_fishy", "resolution": "confirm_genuine"},
        )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# 6. tenancy: another tenant's quarantine is not a queue, not a row, not ours
# ---------------------------------------------------------------------------


async def test_foreign_quarantined_rows_are_invisible_and_unresolvable(
    db: AsyncSession, tenant_ctx
) -> None:
    """Another tenant's quarantine is invisible AND unwritable — proved twice.

    What this test originally got wrong: it asserted the foreign mark survived
    by reading the row under the CALLER's tenant binding. FORCE RLS filters
    ``customers`` on ``app.tenant_id``, so that SELECT matched no row and
    ``extra`` came back ``NULL``; the assertion died on ``'phone_status' in {}``
    while reading as a cleared mark what is in fact the isolation working (the
    endpoint had answered 404 and written nothing). So the queue and the refusal
    stay checked as the caller, and the surviving mark is read as its OWNER,
    where a real clearing would be visible.
    """
    other = Tenant(slug=f"foreign-{uuid.uuid4().hex[:8]}", name="Foreign Tenant")
    db.add(other)
    await db.flush()
    async with _seen_as(db, other.id):
        foreign_id = await _marked(db, other.id, flag=dict(_REVIEW_MARK), name="Foreign")

    own_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK), name="Own")

    async with _client(db, tenant_ctx, WRITE) as client:
        listed = await client.get("/api/v1/customers/contact-data-issues")
        assert listed.status_code == 200, listed.text
        ids = [item["customer_id"] for item in listed.json()["items"]]
        assert ids == [str(own_id)], "the foreign row never surfaces in the queue"

        cross = await client.post(
            RESOLVE_PATH_TPL.format(foreign_id),
            json={"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"},
        )
        assert cross.status_code == 404, cross.text
        assert cross.json()["error"]["code"] == "not_found"

    # A refusal, not a silent partial write. An audit leak IS visible from here:
    # ``write_audit_row`` stamps the CALLER's tenant_id even when the resource id
    # it names belongs to someone else, so this binding is exactly the one that
    # could catch a cross-tenant write. It catches nothing.
    assert await _audit_rows(db, foreign_id) == [], (
        "the 404 wrote an audit row naming another tenant's customer"
    )
    assert "phone_status" in await _flag(db, own_id), "the caller's own row is still quarantined"

    # And the foreign row itself, seen as its owner, still carries every key the
    # migration left, plus the phone column beside it.
    async with _seen_as(db, other.id):
        assert await _flag(db, foreign_id) == {
            **_REVIEW_MARK,
            "revision": "d5a1c7e94b02",
        }, "the foreign mark is untouched"
        assert (
            await db.scalar(select(Customer.phone).where(Customer.id == foreign_id)) == FABRICATED
        ), "a refused resolve may not rewrite another tenant's contact"
        assert await _audit_rows(db, foreign_id) == []


# ---------------------------------------------------------------------------
# 6b. the same rule without a database: the lookup carries the tenant, and the
#     refusal lands BEFORE anything is written.
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _UnscopedQueryShowsForeignRows:
    """A session that behaves like an UNSCOPED query, deliberately.

    It hands the foreign customer to any SELECT over ``customers`` that forgot
    ``customers.tenant_id`` — what a lost predicate, or a BYPASSRLS role, would
    expose in place of the row FORCE RLS hides — and nothing to a scoped one.
    So the cases below go red the moment the service stops filtering by tenant,
    with no database to skip on.
    """

    def __init__(self, row: Customer) -> None:
        self._row = row
        self.statements: list[tuple[str, object]] = []
        self.flushes = 0

    async def execute(self, statement, params=None):  # noqa: ANN001
        sql = " ".join(str(statement).split())
        self.statements.append((sql, params))
        if "FROM customers" in sql:
            return _Result(None if "customers.tenant_id" in sql else self._row)
        return _Result(None)

    async def flush(self) -> None:
        self.flushes += 1


def _foreign_customer() -> Customer:
    return Customer(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Foreign",
        phone=FABRICATED,
        extra={"data_quality": {"m12_contact_backfill": {**_REVIEW_MARK, "revision": "x"}}},
    )


async def test_a_foreign_id_is_refused_before_anything_is_written() -> None:
    """The id off the path is not an authorization: the lookup carries the tenant."""
    foreign = _foreign_customer()
    session = _UnscopedQueryShowsForeignRows(foreign)

    with pytest.raises(NotFoundError):
        await CustomerService.resolve_contact_issue(
            session,  # type: ignore[arg-type]
            uuid.uuid4(),
            foreign.id,
            issue=LEGACY_ISSUE,
            resolution="confirm_genuine",
            actor_user_id=uuid.uuid4(),
        )

    customer_reads = [sql for sql, _ in session.statements if "FROM customers" in sql]
    assert customer_reads, "the resolver must read the row, not trust the path id"
    assert all("customers.tenant_id" in sql for sql in customer_reads), (
        f"a customers read with no tenant predicate: {customer_reads}"
    )
    # Nothing after the refusal: no flush of a mutated JSONB, and no audit INSERT
    # that could name a resource living in another tenant.
    assert session.flushes == 0, session.statements
    assert foreign.extra["data_quality"]["m12_contact_backfill"]["phone_status"] == (
        "needs_review"
    ), "a refused resolve leaves the mark exactly as it found it"


async def test_tenancy_is_checked_before_the_request_body_is_valid() -> None:
    """Order matters: an unknown issue on a foreign id answers 404, not a 400
    that confirms the row exists to someone who cannot see it."""
    foreign = _foreign_customer()
    session = _UnscopedQueryShowsForeignRows(foreign)

    with pytest.raises(NotFoundError):
        await CustomerService.resolve_contact_issue(
            session,  # type: ignore[arg-type]
            uuid.uuid4(),
            foreign.id,
            issue="smells_fishy",
            resolution="confirm_genuine",
            actor_user_id=uuid.uuid4(),
        )
    assert session.flushes == 0


# ---------------------------------------------------------------------------
# 7. the queue itself: mark + raw value + classification + collision peer
# ---------------------------------------------------------------------------


async def test_the_queue_lists_the_mark_the_raw_value_and_the_collision_peer(
    db: AsyncSession, tenant_ctx
) -> None:
    holder = Customer(id=uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, name="Holder", phone=EGYPT)
    db.add(holder)
    await db.flush()
    review_id = await _marked(db, tenant_ctx.tenant_id, flag=dict(_REVIEW_MARK))
    clash_id = await _marked(
        db,
        tenant_ctx.tenant_id,
        phone="00201001234567",
        flag={"phone_collision": {"canonical": EGYPT, "peer_customer_ids": [str(holder.id)]}},
    )

    async with _client(db, tenant_ctx, PII) as client:
        listed = await client.get("/api/v1/customers/contact-data-issues")

    assert listed.status_code == 200, listed.text
    by_id = {item["customer_id"]: item for item in listed.json()["items"]}
    assert set(by_id) == {str(review_id), str(clash_id)}
    review = by_id[str(review_id)]
    assert review["issues"] == [LEGACY_ISSUE]
    assert review["phone"] == FABRICATED, "the raw stored value, unmassaged"
    assert review["phone_state"] == "corrupted"
    assert review["suspected_phone"] == EGYPT
    clash = by_id[str(clash_id)]
    assert clash["issues"] == [COLLISION_ISSUE]
    assert clash["canonical_phone"] == EGYPT
    assert clash["peer_customer_ids"] == [str(holder.id)]


async def test_tombstoned_customers_leave_the_queue(db: AsyncSession, tenant_ctx) -> None:
    """A dead row cannot be worked: resolve refuses it, so the queue must not
    promise it. It is not a quarantined CONTACT any more."""
    archived_id = await _marked(
        db,
        tenant_ctx.tenant_id,
        flag=dict(_REVIEW_MARK),
    )
    survivor = Customer(
        id=uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, name="Survivor", phone=EGYPT
    )
    db.add(survivor)
    await db.flush()
    merged_peer = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_ctx.tenant_id,
        name="Merged away",
        phone="0100-999-8877",
        extra={"data_quality": {"m12_contact_backfill": {**_REVIEW_MARK, "revision": "x"}}},
        merged_into_customer_id=survivor.id,
    )
    db.add(merged_peer)
    await db.flush()
    await db.execute(
        text("UPDATE customers SET deleted_at = now() WHERE id = :cid"),
        {"cid": archived_id},
    )

    async with _client(db, tenant_ctx, WRITE) as client:
        listed = await client.get("/api/v1/customers/contact-data-issues")
        assert listed.json()["items"] == []
        response = await client.post(
            RESOLVE_PATH_TPL.format(archived_id),
            json={"issue": LEGACY_ISSUE, "resolution": "confirm_genuine"},
        )
        assert response.status_code == 404, response.text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
