"""§55-57 — the merchant's DOOR for a chosen retention policy.

The defect this file exists for
------------------------------
``retention.choose_policy`` and ``retention.policy_position`` were complete,
tested, and unreachable: no HTTP route called either of them. The purge gate is
fail-closed on purpose (``BLOCKED_NO_CHOSEN_POLICY`` — every active tenant must
choose before a shared month may be dropped), so a module nobody can answer
produced a sweep that runs forever and always declines. The policy table
existed, the decision code existed, the merchant had no door. That is
governance by docstring, and this repo has already called it twice
(``archive_old_rows``, ``/analytics/overview``).

What is pinned here
-------------------
DB-free (runs locally):

1. Both routes are PUBLISHED and are reachable in the OpenAPI contract — an
   unwired service function is the bug, so the first assertion is the wire.
2. **Tenancy comes from the request context only**: neither operation publishes
   a ``tenant_id`` parameter for a client to set.
3. A tenant that never chose is reported as having no policy, and the gate says
   so out loud (``blocked_reason`` + ``unblock_requires`` naming how many).
4. ``blocked_reason`` is ``evaluate_gate``'s answer for the same counts — read
   back through the real module functions, so the route cannot drift from the
   rule it reports.
5. The write route calls ``retention.choose_policy`` (the module's ONLY writer)
   and audits through ``app.core.audit.write_audit_row``.
6. An illegal horizon, an illegal status, or an unknown data class is a 4xx that
   names the fix, and NOTHING reaches the database or the audit trail — the
   session under test raises the moment it is asked a question.

DB-gated (skips locally without ``DATABASE_URL_APP_ADMIN``; runs in CI):

7. A real choice changes what ``policy_position`` reports AND leaves an audit
   row; a real refusal leaves neither.
8. Pausing withdraws the choice, and the shared gate notices.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.analytics import retention
from app.modules.analytics import router as analytics_router
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

POSITION_PATH = "/api/v1/analytics/retention"
CHOOSE_PATH_TPL = "/api/v1/analytics/retention/policies/{data_class}"
AI_USAGE = retention.AI_USAGE_DATA_CLASS

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")

#: ``(data_class, retention_days, status, last_run_at, updated_at)`` — the column
#: order of ``retention.TENANT_POLICY_ROWS_SQL``.
NO_ROWS: tuple[Any, ...] = ()
CHOSEN_ROW = ((AI_USAGE, 500, "active", None, None),)


# ------------------------------------------------------------- the harness ---


class _Result:
    """The three shapes ``retention`` asks a result for."""

    def __init__(self, rows: tuple[Any, ...]) -> None:
        self._rows = tuple(rows)

    def one(self) -> Any:
        if len(self._rows) != 1:
            raise AssertionError(f"expected exactly one row, got {len(self._rows)}")
        return self._rows[0]

    def all(self) -> tuple[Any, ...]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _RecordingSession:
    """Answers exactly the statements ``retention`` runs, from canned counts.

    Anything else is a test failure: the ROUTER must not own SQL (see
    ``test_the_analytics_router_holds_no_sql``), so a query this class does not
    recognise means a route started writing its own.
    """

    def __init__(
        self,
        *,
        tenant_count: int = 2,
        missing_policies: int = 2,
        max_days: int | None = None,
        policy_rows: tuple[Any, ...] = NO_ROWS,
        chosen_rows: tuple[Any, ...] = NO_ROWS,
    ) -> None:
        self.counts = (tenant_count, missing_policies, max_days)
        self.policy_rows = policy_rows
        self.chosen_rows = chosen_rows
        self.statements: list[str] = []
        self.params_seen: list[dict] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params_seen.append(dict(params or {}))
        if "retention_drop_horizon" in sql:
            return _Result((self.counts,))
        # POLICY_READ_SQL is the narrowed "has chosen" read; TENANT_POLICY_ROWS_SQL
        # is the visible read that must also show a withdrawn (paused) choice.
        if "status = 'active'" in sql:
            return _Result(self.chosen_rows)
        if "data_class = :data_class" in sql:
            wanted = (params or {}).get("data_class")
            return _Result(tuple(r for r in self.policy_rows if r[0] == wanted))
        if "FROM retention_policies" in sql:
            return _Result(self.policy_rows)
        raise AssertionError(f"the routes asked a question nobody owns: {sql[:120]}")


class _ForbiddenSession:
    """Validation must happen before the first query — no silent clamp, no
    half-written policy."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, statement, _params=None):
        self.calls += 1
        raise AssertionError(f"a write reached the database for a refused request: {statement}")


def _app(session, permissions: set[str]):
    async def _ctx() -> TenantContext:
        return TenantContext(
            session=session,
            user=AuthedUser(id=ACTOR, tenant_id=TENANT, role_code="owner"),
            tenant_id=TENANT,
            role_code="owner",
            permission_codes=set(permissions),
        )

    app = create_app()
    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _request(session, method: str, path: str, permissions: set[str], **kw):
    transport = ASGITransport(app=_app(session, permissions))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kw)


async def _get_position(session, permissions: set[str] | None = None):
    return await _request(
        session,
        "GET",
        POSITION_PATH,
        {"analytics:read"} if permissions is None else permissions,
    )


async def _choose(
    session,
    data_class: str = AI_USAGE,
    *,
    body: dict | None = None,
    permissions: set[str] | None = None,
):
    return await _request(
        session,
        "PUT",
        CHOOSE_PATH_TPL.format(data_class=data_class),
        {"analytics:read", "analytics:write"} if permissions is None else permissions,
        json=body if body is not None else {"retention_days": 500, "status": "active"},
    )


class _Recorder:
    """Stands in for ``choose_policy`` / ``write_audit_row`` and says what it got."""

    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []
        self.result = result or {}

    async def __call__(self, *args, **kwargs):
        self.calls.append(args)
        self.kwargs.append(kwargs)
        return self.result if self.result else None


# --------------------------------------------------------- the door exists ---


def test_both_retention_routes_are_published() -> None:
    """RED first: the merchant had no path to answer the consent question."""
    paths = create_app().openapi()["paths"]
    assert POSITION_PATH in paths
    assert "get" in paths[POSITION_PATH]
    choose_path = CHOOSE_PATH_TPL.format(data_class="{data_class}")
    assert choose_path in paths, sorted(p for p in paths if "retention" in p)
    assert "put" in paths[choose_path]


#: The parameters ``identity.deps.get_tenant_ctx`` publishes for EVERY
#: authenticated route: the bearer token and the context selectors it verifies
#: membership for. A retention route adding anything here would be a second way
#: to name a tenant.
_SHARED_CONTEXT_PARAMS = {
    "authorization",
    "x-tenant-id",
    "x-workspace-id",
    "x-location-id",
}


def test_no_route_takes_a_tenant_id_from_the_client() -> None:
    """Tenancy is the request context's, never the caller's.

    ``x-tenant-id`` is the platform-wide context selector — membership-checked
    and RLS-bound by ``get_tenant_ctx`` before any handler runs — and is allowed
    to appear. What is NOT allowed is a ``tenant_id`` path/query/body parameter
    on these two operations, which would let a caller point a governance write
    at somebody else's policy row.
    """
    spec = create_app().openapi()
    choose_path = CHOOSE_PATH_TPL.format(data_class="{data_class}")
    operations = (
        (POSITION_PATH, "get", set()),
        (choose_path, "put", {"data_class"}),
    )
    for path, method, extra in operations:
        published = spec["paths"][path][method]
        names = {p["name"] for p in published.get("parameters", [])}
        assert names == _SHARED_CONTEXT_PARAMS | extra, names
        assert "tenant_id" not in names

    handlers = (analytics_router.retention_position, analytics_router.choose_retention_policy)
    for handler in handlers:
        assert "tenant_id" not in inspect.signature(handler).parameters, handler.__name__
    assert "tenant_id" not in analytics_router.RetentionPolicyChoice.model_fields


# ------------------------------------------- the read route, DB-free -------


async def test_a_tenant_that_never_chose_is_reported_as_having_no_policy() -> None:
    session = _RecordingSession(tenant_count=2, missing_policies=2, max_days=None)
    response = await _get_position(session)
    assert response.status_code == 200, response.text

    payload = response.json()
    entry = next(p for p in payload["policies"] if p["data_class"] == AI_USAGE)
    assert entry["chosen"] is False
    assert entry["status"] is None
    assert entry["retention_days"] is None
    # The value the door offers, and the floor no choice may undercut: readable
    # before the merchant has answered anything.
    assert entry["offered_default_days"] == retention.DEFAULT_RETENTION_DAYS[AI_USAGE]
    assert entry["legal_floor_months"] == 13

    assert payload["blocked_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY
    assert payload["gate"]["may_drop"] is False
    assert payload["gate"]["missing_policies"] == 2
    assert payload["gate"]["tenant_count"] == 2
    assert payload["gate"]["max_days"] is None

    advice = " ".join(payload["unblock_requires"])
    assert "2" in advice, advice
    assert AI_USAGE in advice, advice


async def test_every_policy_read_is_bound_to_the_context_tenant() -> None:
    """RLS is the guarantee, but a read that forgot the explicit filter would be
    invisible until it leaked: every parameterised policy read must carry the
    tenant the context resolved, not one a client named."""
    session = _RecordingSession()
    response = await _get_position(session)
    assert response.status_code == 200, response.text

    tenant_reads = [p for p in session.params_seen if "tenant_id" in p]
    assert tenant_reads, "the position route read no policy at all"
    assert {tuple(sorted(p)) for p in tenant_reads} == {("tenant_id",)}
    assert {p["tenant_id"] for p in tenant_reads} == {str(TENANT)}


async def test_a_chosen_policy_is_reported_with_its_horizon_and_last_run() -> None:
    session = _RecordingSession(
        tenant_count=2,
        missing_policies=0,
        max_days=500,
        policy_rows=CHOSEN_ROW,
        chosen_rows=CHOSEN_ROW,
    )
    payload = (await _get_position(session)).json()
    entry = next(p for p in payload["policies"] if p["data_class"] == AI_USAGE)
    assert entry["chosen"] is True
    assert entry["status"] == "active"
    assert entry["retention_days"] == 500
    assert payload["blocked_reason"] is None
    assert payload["gate"]["max_days"] == 500


@pytest.mark.parametrize(
    ("tenant_count", "missing_policies", "max_days"),
    [
        (0, 0, None),  # nothing to consent
        (3, 1, 500),  # one silent tenant pins the shared month
        (2, 0, 500),  # everybody chose
        (2, 0, 0),  # a horizon that would delete everything
    ],
)
async def test_the_read_route_reports_exactly_what_evaluate_gate_says(
    tenant_count: int, missing_policies: int, max_days: int | None
) -> None:
    """The route may not have an opinion of its own about why it is blocked.

    Both sides are computed from the SAME counts, so a route that invented its
    own reason — or dropped one — fails here.
    """
    session = _RecordingSession(
        tenant_count=tenant_count,
        missing_policies=missing_policies,
        max_days=max_days,
    )
    payload = (await _get_position(session)).json()
    gate = retention.evaluate_gate(
        tenant_count=tenant_count,
        missing_policies=missing_policies,
        max_days=max_days,
    )
    assert payload["gate"] == {
        "tenant_count": gate.tenant_count,
        "missing_policies": gate.missing_policies,
        "max_days": gate.max_days,
        "may_drop": gate.may_drop,
        "reason": gate.reason,
    }
    assert payload["blocked_reason"] == (None if gate.may_drop else gate.reason)
    if not gate.may_drop:
        assert payload["unblock_requires"], "a blocked gate must say what unblocks it"
    else:
        assert payload["unblock_requires"] == []


async def test_the_read_route_needs_the_analytics_read_scope() -> None:
    response = await _get_position(_RecordingSession(), permissions=set())
    assert response.status_code == 403


# ------------------------------------------------ the write route, DB-free --


async def test_choosing_delegates_to_the_modules_only_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route is a door, not a second implementation of the upsert."""
    recorder = _Recorder(
        result={
            "data_class": AI_USAGE,
            "retention_days": 500,
            "status": "active",
            "chosen": True,
        }
    )
    monkeypatch.setattr(retention, "choose_policy", recorder)
    monkeypatch.setattr(analytics_router, "write_audit_row", _Recorder())

    session = _RecordingSession(policy_rows=CHOSEN_ROW, chosen_rows=CHOSEN_ROW)
    response = await _choose(session, body={"retention_days": 500, "status": "active"})

    assert response.status_code == 200, response.text
    assert len(recorder.calls) == 1
    args = recorder.calls[0]
    assert args[0] is session, "the route must use the request session"
    assert args[1] == TENANT, "tenancy comes from the request context"
    assert args[2] == AI_USAGE
    assert recorder.kwargs[0] == {"retention_days": 500, "enabled": True}
    assert response.json()["policy"] == recorder.result


@pytest.mark.parametrize(("status", "enabled"), [("active", True), ("paused", False)])
async def test_the_two_published_statuses_map_to_opt_in_and_opt_out(
    monkeypatch: pytest.MonkeyPatch, status: str, enabled: bool
) -> None:
    # The stand-in mirrors what choose_policy actually returns (data_class,
    # retention_days, status, chosen) so the response model is exercised against
    # a payload the real writer can produce; the assertion below still reads the
    # kwargs, which is what this test is about.
    recorder = _Recorder(
        result={
            "data_class": AI_USAGE,
            "retention_days": 390,
            "status": status,
            "chosen": enabled,
        }
    )
    monkeypatch.setattr(retention, "choose_policy", recorder)
    monkeypatch.setattr(analytics_router, "write_audit_row", _Recorder())
    response = await _choose(_RecordingSession(), body={"retention_days": 390, "status": status})
    assert response.status_code == 200, response.text
    assert recorder.kwargs[0]["enabled"] is enabled


async def test_choosing_is_audited_as_a_permission_to_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every governance write in this repo is audited; a retention choice authorises
    a DELETE of other tenants' shared rows, so it qualifies more than most."""
    monkeypatch.setattr(
        retention,
        "choose_policy",
        # Mirrors the producer (retention.py: choose_policy returns the row it
        # wrote: data_class, retention_days, status, chosen) — a stand-in that
        # returns less than the real writer does would let the route's response
        # model pass against a payload no production call path can produce.
        _Recorder(
            result={
                "data_class": AI_USAGE,
                "retention_days": 500,
                "status": "active",
                "chosen": True,
            }
        ),
    )
    audit = _Recorder()
    monkeypatch.setattr(analytics_router, "write_audit_row", audit)

    await _choose(_RecordingSession(), body={"retention_days": 500, "status": "active"})

    assert len(audit.calls) == 1, "the choice must leave an audit row"
    args = audit.calls[0]
    assert args[1] == TENANT
    assert args[2] == ACTOR, "the acting user is recorded, not a NULL actor"
    assert args[3] == retention.CHOOSE_AUDIT_ACTION
    assert args[4] == retention.CHOOSE_AUDIT_RESOURCE
    assert args[5] == AI_USAGE
    assert audit.kwargs[0]["after"]["retention_days"] == 500


async def test_the_audit_records_the_answer_being_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing a permission-to-delete must be legible afterwards: the row says
    what the tenant had said before, not only what it now says."""
    monkeypatch.setattr(
        retention,
        "choose_policy",
        # Faithful to the producer, as above: this test withdraws (paused), so
        # the writer's own answer carries status/chosen for the withdrawal.
        _Recorder(
            result={
                "data_class": AI_USAGE,
                "retention_days": 900,
                "status": "paused",
                "chosen": False,
            }
        ),
    )
    audit = _Recorder()
    monkeypatch.setattr(analytics_router, "write_audit_row", audit)

    session = _RecordingSession(policy_rows=CHOSEN_ROW, chosen_rows=CHOSEN_ROW)
    await _choose(session, body={"retention_days": 900, "status": "paused"})

    before = audit.kwargs[0]["before"]
    assert before == {"status": "active", "retention_days": 500}
    assert audit.kwargs[0]["after"]["status"] == "paused"


async def test_an_audit_action_name_is_unique_to_the_choice() -> None:
    """A purge already audits under its own action; a merchant reading the trail
    must be able to tell consent from deletion."""
    assert retention.CHOOSE_AUDIT_ACTION != retention.PURGE_AUDIT_ACTION
    assert retention.CHOOSE_AUDIT_ACTION == "retention.policy_chosen"


@pytest.mark.parametrize("days", [0, -1, 3651, 99_999, None, "500x"])
async def test_an_illegal_horizon_is_refused_without_writing_anything(
    monkeypatch: pytest.MonkeyPatch, days: Any
) -> None:
    """§47's posture: refuse at the boundary and name the fix. Never clamp."""
    choose = _Recorder()
    monkeypatch.setattr(retention, "choose_policy", choose)
    monkeypatch.setattr(analytics_router, "write_audit_row", _Recorder())
    session = _ForbiddenSession()

    response = await _choose(session, body={"retention_days": days, "status": "active"})

    assert 400 <= response.status_code < 500, response.status_code
    assert response.status_code == 422, response.text
    assert choose.calls == [], "a refused request reached the ONLY writer"
    assert session.calls == 0, "a refused request touched the database"


@pytest.mark.parametrize("status", ["delete", "ACTIVE", "on", "", None])
async def test_an_unknown_status_is_refused_not_guessed(
    monkeypatch: pytest.MonkeyPatch, status: Any
) -> None:
    choose = _Recorder()
    monkeypatch.setattr(retention, "choose_policy", choose)
    monkeypatch.setattr(analytics_router, "write_audit_row", _Recorder())
    session = _ForbiddenSession()

    response = await _choose(session, body={"retention_days": 500, "status": status})

    assert response.status_code == 422, response.text
    assert choose.calls == []
    assert session.calls == 0


@pytest.mark.parametrize(
    "data_class", ["audit_logs", "orders", "customer_data", "ai_usage ", "AI_USAGE"]
)
async def test_a_store_this_door_cannot_execute_is_refused_naming_the_fix(
    monkeypatch: pytest.MonkeyPatch, data_class: str
) -> None:
    """``audit_logs`` must never be hard-deleted (§57 legal retention); a typo'd
    class would otherwise park a policy row that governs nothing. The row stores
    (``messages``, ``webhook_events``) are NOT in this list any more: the row
    sweep always honoured a chosen policy for them, and the door that lets a
    merchant state one is the gap that closed.

    The refusal names the store it DOES govern, so the caller is not left to
    guess which of the two happened.
    """
    choose = _Recorder()
    monkeypatch.setattr(retention, "choose_policy", choose)
    monkeypatch.setattr(analytics_router, "write_audit_row", _Recorder())
    session = _ForbiddenSession()

    response = await _choose(session, data_class, body={"retention_days": 500, "status": "active"})

    assert 400 <= response.status_code < 500
    assert choose.calls == []
    assert session.calls == 0
    named = str(response.json())
    assert AI_USAGE in named, "the refusal must name the stores that ARE accepted"


def test_the_door_governs_exactly_the_stores_an_executor_can_purge() -> None:
    """A door and a read model must cover the same set: publishing a policy the
    position route cannot show would recreate "a choice nobody can read". And the
    union is exactly the two executors this module owns — months and rows — so
    neither can grow a store the other cannot execute.
    """
    assert retention.CHOOSABLE_DATA_CLASSES == frozenset(
        retention.PARTITIONED_DATA_CLASSES
    ) | frozenset(retention.ROW_LEVEL_DATA_CLASSES)
    assert AI_USAGE in retention.CHOOSABLE_DATA_CLASSES
    assert "audit_logs" not in retention.CHOOSABLE_DATA_CLASSES


async def test_the_write_needs_the_analytics_write_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choose = _Recorder()
    monkeypatch.setattr(retention, "choose_policy", choose)
    session = _ForbiddenSession()
    response = await _choose(session, permissions={"analytics:read"})
    assert response.status_code == 403
    assert choose.calls == []
    assert session.calls == 0


# ---------------------------------------------------- the route vs the gate --
#
# Everything below needs a real PostgreSQL (RLS + the SECURITY DEFINER aggregate).
# It skips locally without DATABASE_URL_APP_ADMIN and runs in CI.


def _context_for(db: AsyncSession, tenant_ctx, permissions: set[str]) -> TenantContext:
    """A request context whose tenancy IS the fixture's, for the DB-gated cases.

    Two things must hold at once there, and they are easy to get wrong separately:
    the ``tenant_id`` the route passes to ``retention`` must be the tenant the
    transaction's ``app.tenant_id`` GUC is bound to (``tenant_ctx`` does that
    binding through ``bind_tenant``), and the session must be the same one the
    GUC was set on. ``get_tenant_ctx`` does both in production; an override does
    neither unless the test says so.
    """
    return TenantContext(
        session=db,
        user=AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes=set(permissions),
    )


def _app_for(db: AsyncSession, tenant_ctx, permissions: set[str]):
    """The app, driven over a REAL database with the fixture's own tenancy.

    The module-level ``_app`` is for the DB-free cases, where the fabricated
    ``TENANT``/``ACTOR`` constants cost nothing. Over a real database both
    constants break, in two different ways, and CI 35959902953 showed them
    together:

    * ``retention_policies`` is FORCE RLS, so a row whose ``tenant_id`` is not
      the transaction's ``app.tenant_id`` GUC — which the ``db``/``tenant_ctx``
      fixtures bind to ``tenant_ctx.tenant_id`` — is refused on INSERT with
      "new row violates row-level security policy".
    * ``audit_logs.actor_user_id`` carries a foreign key to ``users``, so the
      fabricated ``ACTOR`` is a ``ForeignKeyViolationError`` on the audit row
      every write appends (§66).

    The override is named ``_override`` and not ``_ctx``: an earlier version
    shadowed the module-level builder with its own zero-arg override, and
    Python made the inner name local to the scope, so the builder call resolved
    to the override — ``TypeError: _ctx() takes 0 positional arguments but 3
    were given``.
    """
    app = create_app()

    async def _override() -> TenantContext:
        return _context_for(db, tenant_ctx, permissions)

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


async def _position_over_real_db(db: AsyncSession, tenant_ctx) -> dict:
    transport = ASGITransport(app=_app_for(db, tenant_ctx, {"analytics:read", "analytics:write"}))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(POSITION_PATH)
    assert response.status_code == 200, response.text
    return response.json()


async def _aggregate(db: AsyncSession) -> tuple[int, int, int | None]:
    """The counts the database computes, read directly — the third opinion in the
    drift guard: SQL, ``evaluate_gate``, and the route."""
    row = (
        await db.execute(
            sa.text(
                "SELECT tenant_count, missing_policies, max_days "
                "FROM public.retention_drop_horizon(:dc)"
            ),
            {"dc": AI_USAGE},
        )
    ).one()
    return int(row[0]), int(row[1]), None if row[2] is None else int(row[2])


async def test_a_tenant_that_never_chose_reads_as_no_policy_and_blocks(
    db: AsyncSession, tenant_ctx
) -> None:
    await db.execute(
        sa.text("DELETE FROM retention_policies WHERE tenant_id = :t AND data_class = :c"),
        {"t": str(tenant_ctx.tenant_id), "c": AI_USAGE},
    )
    await db.flush()

    payload = await _position_over_real_db(db, tenant_ctx)
    entry = next(p for p in payload["policies"] if p["data_class"] == AI_USAGE)
    assert entry["chosen"] is False
    assert entry["status"] is None

    count, missing, max_days = await _aggregate(db)
    gate = retention.evaluate_gate(tenant_count=count, missing_policies=missing, max_days=max_days)
    assert payload["blocked_reason"] == (None if gate.may_drop else gate.reason)
    assert payload["gate"]["missing_policies"] == missing
    assert missing >= 1, "a tenant that never chose must count as not chosen"


async def test_choosing_a_legal_policy_moves_position_and_leaves_an_audit_row(
    db: AsyncSession, tenant_ctx
) -> None:
    await db.execute(
        sa.text("DELETE FROM retention_policies WHERE tenant_id = :t AND data_class = :c"),
        {"t": str(tenant_ctx.tenant_id), "c": AI_USAGE},
    )
    await db.flush()
    before_count, before_missing, _ = await _aggregate(db)

    app = _app_for(db, tenant_ctx, {"analytics:read", "analytics:write"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        chosen = await client.put(
            CHOOSE_PATH_TPL.format(data_class=AI_USAGE),
            json={"retention_days": 390, "status": "active"},
        )
        assert chosen.status_code == 200, chosen.text
        assert chosen.json()["policy"]["retention_days"] == 390

    position = await retention.policy_position(db, tenant_ctx.tenant_id)
    entry = next(p for p in position if p["data_class"] == AI_USAGE)
    assert entry["chosen"] is True
    assert entry["retention_days"] == 390
    assert entry["status"] == "active"

    after_count, after_missing, after_max = await _aggregate(db)
    assert after_count == before_count
    assert after_missing == before_missing - 1, "this tenant stopped pinning the month"
    assert after_max == 390

    audits = (
        await db.execute(
            sa.text(
                "SELECT action, resource_type, resource_id, actor_user_id, after::text "
                "FROM audit_logs WHERE action = :a AND tenant_id = :t"
            ),
            {"a": retention.CHOOSE_AUDIT_ACTION, "t": str(tenant_ctx.tenant_id)},
        )
    ).all()
    assert len(audits) == 1, audits
    assert audits[0][1] == retention.CHOOSE_AUDIT_RESOURCE
    assert audits[0][2] == AI_USAGE
    assert str(tenant_ctx.user.id) == str(audits[0][3])
    assert "390" in audits[0][4]

    # And the read door now agrees with the module.
    payload = await _position_over_real_db(db, tenant_ctx)
    assert next(p for p in payload["policies"] if p["data_class"] == AI_USAGE)["chosen"]


async def test_pausing_withdraws_the_choice_from_the_shared_gate(
    db: AsyncSession, tenant_ctx
) -> None:
    await retention.choose_policy(
        db, tenant_ctx.tenant_id, AI_USAGE, retention_days=390, enabled=True
    )
    _, chosen_missing, _ = await _aggregate(db)

    app = _app_for(db, tenant_ctx, {"analytics:read", "analytics:write"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        paused = await client.put(
            CHOOSE_PATH_TPL.format(data_class=AI_USAGE),
            json={"retention_days": 390, "status": "paused"},
        )
        assert paused.status_code == 200, paused.text

    _, missing, max_days = await _aggregate(db)
    assert missing == chosen_missing + 1
    position = await retention.policy_position(db, tenant_ctx.tenant_id)
    entry = next(p for p in position if p["data_class"] == AI_USAGE)
    assert entry["chosen"] is False
    # The horizon the tenant gave is still VISIBLE after opting out — a withdrawn
    # choice must not look like a never-made one.
    assert entry["status"] == "paused"
    assert entry["retention_days"] == 390
    assert max_days is None or max_days > 0  # this tenant's 390 no longer counts


async def test_an_illegal_choice_writes_no_policy_and_no_audit_row(
    db: AsyncSession, tenant_ctx
) -> None:
    await db.execute(
        sa.text("DELETE FROM retention_policies WHERE tenant_id = :t AND data_class = :c"),
        {"t": str(tenant_ctx.tenant_id), "c": AI_USAGE},
    )
    await db.flush()

    app = _app_for(db, tenant_ctx, {"analytics:read", "analytics:write"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        refused = await client.put(
            CHOOSE_PATH_TPL.format(data_class=AI_USAGE),
            json={"retention_days": 0, "status": "active"},
        )
        assert refused.status_code == 422, refused.text

    rows = (
        await db.execute(
            sa.text(
                "SELECT count(*) FROM retention_policies WHERE tenant_id = :t AND data_class = :c"
            ),
            {"t": str(tenant_ctx.tenant_id), "c": AI_USAGE},
        )
    ).scalar_one()
    assert rows == 0
    audits = (
        await db.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE action = :a AND tenant_id = :t"),
            {"a": retention.CHOOSE_AUDIT_ACTION, "t": str(tenant_ctx.tenant_id)},
        )
    ).scalar_one()
    assert audits == 0


async def test_a_second_choice_replaces_the_first_rather_than_contradicting_it(
    db: AsyncSession, tenant_ctx
) -> None:
    """``UNIQUE (tenant_id, data_class)`` is the whole reason "the policy" has one
    answer; the route must not grow a second row per call."""
    app = _app_for(db, tenant_ctx, {"analytics:read", "analytics:write"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for days in (390, 500):
            response = await client.put(
                CHOOSE_PATH_TPL.format(data_class=AI_USAGE),
                json={"retention_days": days, "status": "active"},
            )
            assert response.status_code == 200, response.text

    rows = (
        await db.execute(
            sa.text(
                "SELECT retention_days, status FROM retention_policies "
                "WHERE tenant_id = :t AND data_class = :c"
            ),
            {"t": str(tenant_ctx.tenant_id), "c": AI_USAGE},
        )
    ).all()
    assert len(rows) == 1, "one tenant may not have two answers for one store"
    assert rows[0][0] == 500
