"""§52/§57 — a CHOSEN policy must reach the ROW-level stores, not only months.

The gap this file exists for
---------------------------
``docs/PII_DATA_MAP.md`` names three stores the retention worker deletes by row:
``messages`` (conversation content — the PII-heaviest table in the system),
``webhook_events`` and ``ai_usage``. ``retention_worker.run_once`` honours a
tenant's ``retention_policies`` row for all three, but the only surface that can
CREATE such a row — ``analytics/retention.CHOOSABLE_DATA_CLASSES`` behind
``PUT /analytics/retention/policies/{data_class}`` — was scoped to the
partitioned store. So the executor read a policy nobody could write: the chosen
horizon for a conversation body did not exist as a question the merchant could
answer, and §57's "archive per chosen policy" was true only for the one table
that holds no content at all.

The fix has to be one machine, not two, so what is pinned below is:

1. **One policy table, one writer, one gate.** Row stores join
   :data:`CHOOSABLE_DATA_CLASSES`, and the SAME pure rule
   (``evaluate_gate`` -> ``BLOCKED_NO_ACTIVE_TENANTS`` /
   ``BLOCKED_NO_CHOSEN_POLICY`` / ``BLOCKED_NO_POSITIVE_HORIZON``) decides a row
   purge. The worker keeps no private copy of the horizon vocabulary, and the
   allowlist of deletable tables exists once.
2. **The chosen policy is the only horizon.** There is no TTL in config and no
   fallback default applied at delete time: absent or ``paused`` means nothing
   goes, and an un-answered question must never look like permission.
3. **Bounded, repeatable, idempotent.** Every statement is ``LIMIT``-shaped with
   an explicit tenant predicate, inside the caller's tenant-bound transaction,
   and the sweep caps how many batches one tenant may spend in one run so a
   backlogged store cannot hold a hot table's transaction open.
4. **Rows another rule keeps must survive.** §24 says a dead-lettered ingress
   row awaits human hands; §130 says a message whose provider outcome is
   unobservable is still being reconciled. Those rows are excluded by a
   per-store keep predicate that the DELETE must always carry.
5. **A destructive act leaves a trail.** The partition purge audits; a row purge
   that deletes thousands of conversation bodies and audits nothing is the §66
   hole, so an audit row is written for a non-zero purge and for nothing else.

DB-free cases run everywhere (the session is a scripted double, the routes are
driven through ASGITransport). The ones that need real rows and real RLS are
gated on ``DATABASE_URL_APP_ADMIN`` and are proven in CI.
"""

from __future__ import annotations

import inspect
import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.main import create_app
from app.modules.analytics import retention
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.workers import retention_worker

MESSAGES = "messages"
WEBHOOK_EVENTS = "webhook_events"
ATTACHMENTS = "attachments"
LEADS = "leads"
AI_USAGE = retention.AI_USAGE_DATA_CLASS
POSITION_PATH = "/api/v1/analytics/retention"
CHOOSE_PATH_TPL = "/api/v1/analytics/retention/policies/{data_class}"

TENANT = uuid.UUID("66666666-6666-6666-6666-666666666666")
ACTOR = uuid.UUID("77777777-7777-7777-7777-777777777777")


# ------------------------------------------------------------- the doubles ---


class _Result:
    def __init__(self, rows: tuple[Any, ...] = (), rowcount: int = 0) -> None:
        self._rows = tuple(rows)
        self.rowcount = rowcount

    def all(self) -> tuple[Any, ...]:
        return self._rows

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        if len(self._rows) != 1:
            raise AssertionError(f"expected one row, got {len(self._rows)}")
        return self._rows[0]

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None

    def scalar_one(self) -> Any:
        return self.one()[0]


class _PurgeSession:
    """Scripted double for the statements ``purge_row_store`` may run.

    It answers ONLY the shapes the module owns; anything else is a loud failure,
    because a purge that starts asking its own questions has stopped being the
    one path the gate governs. The one exception is the §66 audit append, which
    the module is REQUIRED to make and which is counted so a test can see it.
    """

    def __init__(
        self,
        *,
        tenant_active: bool = True,
        policy: tuple[int | None, str | None] | None = (365, "active"),
        rowcounts: list[int] | None = None,
        media_rows: tuple[Any, ...] = (),
    ) -> None:
        self.tenant_active = tenant_active
        self.policy = policy
        self.rowcounts = list(rowcounts or [])
        self.media_rows = media_rows
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.audit_writes = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = dict(params or {})
        self.statements.append(sql)
        self.params.append(params)
        if "FROM tenants" in sql:
            return _Result(((self.tenant_active,),))
        if "INSERT INTO audit_logs" in sql:
            self.audit_writes += 1
            return _Result()
        if "retention_policies" in sql and "data_class" in params:
            return _Result((self.policy,) if self.policy is not None else ())
        if sql.strip().upper().startswith("SELECT") and "storage_key" in sql:
            # §52 media gather. Empty by default: a batch that carries no media
            # must purge exactly like it did before this path existed, which is
            # what most of this file asserts. The media cases live in
            # tests/test_media_and_lead_retention.py.
            return _Result(self.media_rows)
        if sql.strip().upper().startswith("DELETE"):
            return _Result(rowcount=self.rowcounts.pop(0) if self.rowcounts else 0)
        raise AssertionError(f"unexpected statement from the purge path: {sql[:140]}")


class _RecordingPositionSession:
    """Answers the three reads ``policy_position`` runs over a tenant."""

    def __init__(self, *, rows: tuple[Any, ...] = (), chosen: tuple[Any, ...] = ()) -> None:
        self.counts = (1, max(0, 1 - len(chosen)), None if not chosen else rows[0][1])
        self.rows = rows
        self.chosen = chosen
        self.statements: list[str] = []
        self.params_seen: list[dict] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params_seen.append(dict(params or {}))
        if "retention_drop_horizon" in sql:
            return _Result((self.counts,))
        if "status = 'active'" in sql:
            return _Result(self.chosen)
        if "FROM retention_policies" in sql:
            return _Result(self.rows)
        raise AssertionError(f"the read surface asked an unknown question: {sql[:140]}")


class _ForbiddenSession:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, statement, _params=None):
        self.calls += 1
        raise AssertionError(f"a refused request reached the database: {statement}")


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


class _Recorder:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []
        self.result = result or {}

    async def __call__(self, *args, **kwargs):
        self.calls.append(args)
        self.kwargs.append(kwargs)
        return self.result or None


# ================================================ 1. one gate, one allowlist ==


def test_row_stores_are_choosable() -> None:
    """RED first: the door refused the stores whose rows the worker deletes."""
    assert MESSAGES in retention.CHOOSABLE_DATA_CLASSES
    assert WEBHOOK_EVENTS in retention.CHOOSABLE_DATA_CLASSES
    assert AI_USAGE in retention.CHOOSABLE_DATA_CLASSES
    # §57's legal retention is a boundary, not an oversight.
    assert "audit_logs" not in retention.CHOOSABLE_DATA_CLASSES
    assert "orders" not in retention.CHOOSABLE_DATA_CLASSES
    assert "customers" not in retention.CHOOSABLE_DATA_CLASSES


def test_the_row_allowlist_exists_once_and_the_worker_borrows_it() -> None:
    """Two copies of "which tables may a purge touch" is how the wrong one drifts."""
    row_stores = retention.ROW_LEVEL_DATA_CLASSES
    assert set(row_stores) == {
        ATTACHMENTS,
        MESSAGES,
        AI_USAGE,
        WEBHOOK_EVENTS,
        LEADS,
    }
    assert dict(retention_worker._RETENTABLE) == {
        dc: (spec.table, spec.ts_column) for dc, spec in row_stores.items()
    }
    for dc, spec in row_stores.items():
        assert spec.data_class == dc
        assert spec.table == dc, "the allowlist maps to a real table, never to a name from data"
    # A child whose rows leave with a parent's cascade is declared BEFORE it, so
    # the sweep's dependency order comes from this one readable list.
    assert list(row_stores).index(ATTACHMENTS) < list(row_stores).index(MESSAGES)


def test_every_executable_store_is_reachable_from_the_door() -> None:
    """The door must govern exactly what some executor can carry out: a class in
    one set and not the other is either a dead policy row or an unpoliced delete.
    """
    assert retention.CHOOSABLE_DATA_CLASSES == frozenset(retention.PARTITIONED_DATA_CLASSES) | (
        frozenset(retention.ROW_LEVEL_DATA_CLASSES)
    )


def test_the_offered_default_for_messages_is_the_pii_maps_own_number() -> None:
    """§52/§57 never state a duration; ``docs/PII_DATA_MAP.md`` does, per store
    ("messages | conversation content | PII | policy (default 365d)"), and an
    undocumented store gets NO offered default rather than an invented one.
    """
    assert retention.DEFAULT_RETENTION_DAYS[MESSAGES] == 365
    assert WEBHOOK_EVENTS not in retention.DEFAULT_RETENTION_DAYS
    # Every offered number must be traceable where it is written down, not here.
    source = retention.DEFAULT_RETENTION_SOURCE
    for data_class in retention.DEFAULT_RETENTION_DAYS:
        assert data_class in source, f"{data_class}'s default has no cited source"
    assert "365" in source


# ==================================== 2. the chosen policy is the only horizon ==


def test_an_absent_policy_is_a_refusal_not_a_default() -> None:
    gate = retention.evaluate_row_gate(tenant_active=True, retention_days=None, status=None)
    assert gate.may_drop is False
    assert gate.reason == retention.BLOCKED_NO_CHOSEN_POLICY


def test_a_paused_policy_is_a_withdrawn_choice() -> None:
    gate = retention.evaluate_row_gate(tenant_active=True, retention_days=365, status="paused")
    assert gate.may_drop is False
    assert gate.reason == retention.BLOCKED_NO_CHOSEN_POLICY


def test_a_zero_horizon_refuses_before_it_deletes_everything() -> None:
    """The migration's days CHECK is ``NOT VALID``, so a legacy 0 can still reach
    the executor: the gate has to catch it, not the boundary that wrote it.
    """
    for days in (0, -5):
        gate = retention.evaluate_row_gate(
            tenant_active=True, retention_days=days, status=retention.POLICY_ACTIVE
        )
        assert gate.may_drop is False
        assert gate.reason == retention.BLOCKED_NO_POSITIVE_HORIZON


def test_an_inert_tenant_consentsto_nothing() -> None:
    gate = retention.evaluate_row_gate(
        tenant_active=False, retention_days=365, status=retention.POLICY_ACTIVE
    )
    assert gate.reason == retention.BLOCKED_NO_ACTIVE_TENANTS


def test_the_row_gate_is_the_same_rule_as_the_month_gate() -> None:
    """One pure decision, two shapes of input — not a second vocabulary."""
    row = retention.evaluate_row_gate(
        tenant_active=True, retention_days=365, status=retention.POLICY_ACTIVE
    )
    month = retention.evaluate_gate(
        tenant_count=1, missing_policies=0, max_days=365
    )
    assert row.reason == month.reason == retention.REASON_OK
    assert row.may_drop is True
    assert row.max_days == 365
    assert "evaluate_gate" in inspect.getsource(retention.evaluate_row_gate)


def test_the_worker_has_no_horizon_of_its_own() -> None:
    """No TTL, no config fallback: the ONLY number that can bound a row purge is
    the horizon the tenant chose, read from ``retention_policies``.
    """
    src = pathlib.Path(retention_worker.__file__).read_text(encoding="utf-8")
    assert "timedelta(days=" not in src, "a hard-coded horizon beside the chosen one"
    assert "get_settings" not in src
    assert "purge_row_store" in src, "the worker must delegate to the gated executor"


async def test_a_blocked_purge_deletes_nothing_and_reads_no_rows() -> None:
    for policy, reason in (
        (None, retention.BLOCKED_NO_CHOSEN_POLICY),
        ((365, "paused"), retention.BLOCKED_NO_CHOSEN_POLICY),
        ((0, "active"), retention.BLOCKED_NO_POSITIVE_HORIZON),
    ):
        session = _PurgeSession(policy=policy)
        result = await retention.purge_row_store(session, TENANT, MESSAGES)
        assert result["deleted"] == 0
        assert result["skipped_reason"] == reason
        assert not [s for s in session.statements if s.strip().upper().startswith("DELETE")]


async def test_a_purge_for_a_store_with_no_executor_refuses() -> None:
    session = _PurgeSession()
    result = await retention.purge_row_store(session, TENANT, "audit_logs")
    assert result["deleted"] == 0
    assert result["skipped_reason"] == retention.REASON_NOT_A_ROW_STORE
    assert session.statements == [], "a store with no executor must not even be looked at"


# =========================================== 3. bounded, repeatable, idempotent ==


async def test_a_chosen_horizon_deletes_only_rows_past_the_boundary() -> None:
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session = _PurgeSession(policy=(365, "active"), rowcounts=[2])
    result = await retention.purge_row_store(session, TENANT, MESSAGES, now=now)

    deletes = [s for s in session.statements if s.strip().upper().startswith("DELETE")]
    assert len(deletes) == 1, deletes
    sql = deletes[0]
    assert "FROM messages" in sql
    assert "created_at < :cutoff" in sql
    assert "tenant_id = :tenant_id" in sql
    assert result["horizon_days"] == 365
    assert result["cutoff"] == (now - timedelta(days=365)).isoformat()
    assert result["deleted"] == 2
    # Unpatched: a delete this real must reach the audit writer on its own.
    assert session.audit_writes == 1


async def test_every_delete_is_limited_and_carries_the_tenant() -> None:
    """Never an unbounded DELETE against a live table, and never a cross-tenant
    one: the explicit predicate is belt-and-suspenders next to RLS because
    ``webhook_events`` resolves its tenant itself (§130).
    """
    session = _PurgeSession(
        policy=(30, "active"), rowcounts=[500, 500, 7]
    )
    result = await retention.purge_row_store(session, TENANT, MESSAGES)
    deletes = [s for s in session.statements if s.strip().upper().startswith("DELETE")]
    assert len(deletes) == 3, deletes
    assert all("LIMIT" in s for s in deletes)
    assert all("tenant_id = :tenant_id" in s for s in deletes)
    assert result["deleted"] == 1007
    assert result["truncated"] is False


async def test_one_run_cannot_drain_a_hot_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """The batch cap is the difference between a sweep and a lockout: the rest of
    the backlog is the next run's problem, and the horizon is an absolute
    timestamp, so continuing is idempotent.
    """
    monkeypatch.setattr(retention, "ROW_PURGE_BATCH_SIZE", 2)
    monkeypatch.setattr(retention, "ROW_PURGE_MAX_BATCHES", 3)
    session = _PurgeSession(policy=(365, "active"), rowcounts=[2, 2, 2])
    result = await retention.purge_row_store(session, TENANT, MESSAGES)

    deletes = [s for s in session.statements if s.strip().upper().startswith("DELETE")]
    assert len(deletes) == 3, "the sweep kept going past its cap"
    assert result["deleted"] == 6
    assert result["truncated"] is True


async def test_the_batch_size_is_named_and_small() -> None:
    assert retention.ROW_PURGE_BATCH_SIZE == 500
    assert 0 < retention.ROW_PURGE_MAX_BATCHES <= 100


# ====================================== 4. rows another rule keeps must survive ==


async def test_messages_still_being_reconciled_survive_the_purge() -> None:
    """§130: a message whose provider outcome is ``unknown``/``sending`` is still
    evidence the reconciler works on; retention must not retire it.
    """
    session = _PurgeSession(policy=(365, "active"), rowcounts=[1])
    await retention.purge_row_store(session, TENANT, MESSAGES)
    sql = next(s for s in session.statements if s.strip().upper().startswith("DELETE"))
    assert "status NOT IN ('sending', 'unknown')" in sql, sql


async def test_a_dead_lettered_ingress_row_survives_the_purge() -> None:
    """§24: ``dead`` awaits human hands (replay/ignore/resolve). Only the terminal
    close-outs are eligible to age out.
    """
    session = _PurgeSession(policy=(90, "active"), rowcounts=[1])
    await retention.purge_row_store(session, TENANT, WEBHOOK_EVENTS)
    sql = next(s for s in session.statements if s.strip().upper().startswith("DELETE"))
    assert "processing_status IN ('processed', 'ignored', 'resolved')" in sql, sql
    assert "received_at < :cutoff" in sql


def test_the_keep_predicates_are_documented_on_the_store_spec() -> None:
    """A keep rule that is not named where the purge reads it is a rule nobody
    re-implements.
    """
    for dc in (MESSAGES, WEBHOOK_EVENTS):
        spec = retention.ROW_LEVEL_DATA_CLASSES[dc]
        assert spec.keep and spec.keep_reason, dc
        assert "§" in spec.keep_reason, dc
    assert retention.ROW_LEVEL_DATA_CLASSES[AI_USAGE].keep is None


# ================================================== 5. a purge leaves a trail ===


async def test_a_non_zero_row_purge_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _Recorder()
    monkeypatch.setattr(retention, "write_audit_row", audit)
    session = _PurgeSession(policy=(365, "active"), rowcounts=[4])
    await retention.purge_row_store(session, TENANT, MESSAGES)

    assert len(audit.calls) == 1, "deleting conversation bodies silently is the §66 hole"
    args = audit.calls[0]
    assert args[1] == TENANT, "the tenant is the row owner"
    assert args[2] is None, "a sweep has no human actor — the source column says worker"
    assert args[3] == retention.ROW_PURGE_AUDIT_ACTION
    assert args[4] == retention.ROW_PURGE_AUDIT_RESOURCE
    assert args[5] == MESSAGES
    assert audit.kwargs[0]["after"]["deleted"] == 4
    assert audit.kwargs[0]["after"]["horizon_days"] == 365


async def test_an_empty_purge_writes_no_audit_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """An audit trail that records nothing happening cannot be read as evidence
    of anything; the sweep runs daily.
    """
    audit = _Recorder()
    monkeypatch.setattr(retention, "write_audit_row", audit)
    session = _PurgeSession(policy=(365, "active"), rowcounts=[0])
    result = await retention.purge_row_store(session, TENANT, MESSAGES)
    assert result["deleted"] == 0
    assert audit.calls == []


def test_the_row_purge_action_is_distinct_from_the_month_drop() -> None:
    assert retention.ROW_PURGE_AUDIT_ACTION != retention.PURGE_AUDIT_ACTION
    assert retention.ROW_PURGE_AUDIT_ACTION == "retention.rows_purged"


# ================================================= the worker delegates, too ===


class _Policy:
    def __init__(self, data_class: str, days: int | None, status: str = "active") -> None:
        self.data_class = data_class
        self.retention_days = days
        self.status = status
        self.last_run_at = None


class _SweepSession:
    """``run_once``'s ORM enumeration, then the gated executor's own statements."""

    def __init__(self, policies: list[_Policy], rowcounts: list[int] | None = None) -> None:
        self.policies = policies
        self.rowcounts = list(rowcounts or [])
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.audit_writes = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = dict(params or {})
        self.statements.append(sql)
        self.params.append(params)
        if "FROM tenants" in sql:
            return _Result(((True,),))
        if "INSERT INTO audit_logs" in sql:
            self.audit_writes += 1
            return _Result()
        if "retention_policies" in sql and "data_class" in params:
            match = next(
                (p for p in self.policies if p.data_class == params["data_class"]), None
            )
            return _Result(
                ((match.retention_days, match.status),) if match else ()
            )
        if "retention_policies" in sql:
            return _Result(tuple(self.policies))
        if sql.strip().upper().startswith("SELECT") and "storage_key" in sql:
            # §52 media gather — see _PurgeSession. No media rows here.
            return _Result(())
        if sql.strip().upper().startswith("DELETE"):
            return _Result(rowcount=self.rowcounts.pop(0) if self.rowcounts else 0)
        raise AssertionError(f"unexpected statement: {sql[:140]}")


async def test_run_once_reports_a_paused_policy_instead_of_ignoring_it() -> None:
    """A row that quietly vanished from the summary is how "nothing was chosen"
    becomes invisible to whoever is watching the sweep.
    """
    session = _SweepSession([_Policy(MESSAGES, 365, status="paused")])
    summary = await retention_worker.RetentionWorker.run_once(session, TENANT)
    assert summary["policies"] == 0
    assert summary["deleted"] == {}
    assert summary["skipped"] == [
        {"data_class": MESSAGES, "reason": retention.BLOCKED_NO_CHOSEN_POLICY}
    ]
    assert not [s for s in session.statements if s.strip().upper().startswith("DELETE")]


async def test_run_once_still_skips_a_class_it_has_no_executor_for() -> None:
    session = _SweepSession([_Policy("orders", 30)])
    summary = await retention_worker.RetentionWorker.run_once(session, TENANT)
    assert summary["skipped"] == [
        {"data_class": "orders", "reason": retention.REASON_NOT_A_ROW_STORE}
    ]
    assert summary["policies"] == 0


async def test_run_once_applies_the_chosen_horizon_and_stamps_the_policy() -> None:
    policy = _Policy(MESSAGES, 365)
    session = _SweepSession([policy], rowcounts=[500, 12])
    summary = await retention_worker.RetentionWorker.run_once(session, TENANT)
    assert summary["policies"] == 1
    assert summary["deleted"] == {MESSAGES: 512}
    assert summary["skipped"] == []
    assert policy.last_run_at is not None
    assert session.audit_writes == 1, "the sweep's deletes must leave the §66 trail"


# ==================================================== 6. the merchant's door ===


async def test_the_read_surface_lists_the_row_stores() -> None:
    session = _RecordingPositionSession()
    response = await _request(session, "GET", POSITION_PATH, {"analytics:read"})
    assert response.status_code == 200, response.text
    by_class = {p["data_class"]: p for p in response.json()["policies"]}
    assert {MESSAGES, WEBHOOK_EVENTS, AI_USAGE} <= set(by_class)
    for dc in (MESSAGES, WEBHOOK_EVENTS):
        entry = by_class[dc]
        assert entry["chosen"] is False
        assert entry["purge_paths"] == ["row"], entry
        assert entry["shared_gate_reason"] is None, (
            "a row store is this tenant's own rows — another tenant's silence "
            "must never be reported as blocking it"
        )
        assert entry["row_gate_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY
    ai = by_class[AI_USAGE]
    assert ai["purge_paths"] == ["row", "partition"], ai
    assert ai["legal_floor_months"] == 13


async def test_a_row_store_can_be_chosen_through_the_same_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder(
        result={"data_class": MESSAGES, "retention_days": 365, "status": "active"}
    )
    monkeypatch.setattr(retention, "choose_policy", recorder)
    audit = _Recorder()
    monkeypatch.setattr("app.modules.analytics.router.write_audit_row", audit)

    session = _RecordingPositionSession()
    response = await _request(
        session,
        "PUT",
        CHOOSE_PATH_TPL.format(data_class=MESSAGES),
        {"analytics:read", "analytics:write"},
        json={"retention_days": 365, "status": "active"},
    )
    assert response.status_code == 200, response.text
    assert len(recorder.calls) == 1
    assert recorder.calls[0][2] == MESSAGES
    assert recorder.kwargs[0] == {"retention_days": 365, "enabled": True}
    assert len(audit.calls) == 1
    assert audit.calls[0][5] == MESSAGES


async def test_the_door_after_row_stores_still_refuses_an_unknown_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for data_class in ("audit_logs", "conversations", "messages ", "MESSAGES", "orders"):
        choose = _Recorder()
        monkeypatch.setattr(retention, "choose_policy", choose)
        session = _ForbiddenSession()
        response = await _request(
            session,
            "PUT",
            CHOOSE_PATH_TPL.format(data_class=data_class),
            {"analytics:read", "analytics:write"},
            json={"retention_days": 365, "status": "active"},
        )
        assert 400 <= response.status_code < 500, (data_class, response.status_code)
        assert choose.calls == []
        assert session.calls == 0
        named = str(response.json())
        assert MESSAGES in named, "the refusal must name the stores it now accepts"


async def test_the_door_still_demands_its_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retention, "choose_policy", _Recorder())
    read = await _request(_RecordingPositionSession(), "GET", POSITION_PATH, set())
    assert read.status_code == 403
    write = await _request(
        _ForbiddenSession(),
        "PUT",
        CHOOSE_PATH_TPL.format(data_class=MESSAGES),
        {"analytics:read"},
        json={"retention_days": 365, "status": "active"},
    )
    assert write.status_code == 403


async def test_the_shared_month_advice_does_not_blame_a_row_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``retention_drop_horizon`` counts a store; a row store is never part of a
    shared month, so telling a merchant that ``messages`` pins one would be a lie
    that sends them to the wrong fix.
    """
    session = _RecordingPositionSession()
    session.counts = (3, 1, 500)
    response = await _request(session, "GET", POSITION_PATH, {"analytics:read"})
    payload = response.json()
    assert payload["blocked_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY
    advice = " ".join(payload["unblock_requires"])
    assert AI_USAGE in advice
    assert MESSAGES not in advice, advice


def test_the_module_still_owns_no_cross_module_import() -> None:
    """The ratchet is at 94 and does not move for a purge path: the policy rows
    and the tenant liveness probe are bound raw SQL, the audit goes through core.
    """
    src = pathlib.Path(retention.__file__).read_text(encoding="utf-8")
    assert "from app.modules" not in src
    assert "import app.modules" not in src
    assert "from app.workers" not in src
    assert "app.core.audit" in inspect.getsource(retention)


# =============================================== DB-gated: real rows, real RLS ==
#
# Everything below needs PostgreSQL (RLS + the seeded stores). It skips locally
# without DATABASE_URL_APP_ADMIN and is what proves CI.


async def _seed_message(
    db: AsyncSession, tenant_id, *, body: str, age_days: int, status: str = "received"
) -> uuid.UUID:
    from app.modules.conversations.models import Conversation, Message
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_id, name=f"R-{uuid.uuid4().hex[:8]}")
    db.add(customer)
    await db.flush()
    conversation = Conversation(
        tenant_id=tenant_id, customer_id=customer.id, channel="webchat", status="closed"
    )
    db.add(conversation)
    await db.flush()
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body=body,
        status=status,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(message)
    await db.flush()
    return message.id


async def _seed_ingress_event(
    db: AsyncSession, tenant_id, *, age_days: int, processing_status: str
) -> uuid.UUID:
    from app.modules.platform.models import WebhookEvent

    event = WebhookEvent(
        tenant_id=tenant_id,
        provider="whatsapp",
        external_event_id=uuid.uuid4().hex,
        signature_valid=True,
        payload={},
        processing_status=processing_status,
        received_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(event)
    await db.flush()
    return event.id


async def _clear_policy(db: AsyncSession, tenant_id, data_class: str) -> None:
    await db.execute(
        sa.text(
            "DELETE FROM retention_policies WHERE tenant_id = :t AND data_class = :c"
        ),
        {"t": str(tenant_id), "c": data_class},
    )
    await db.flush()


async def _exists(db: AsyncSession, table: str, row_id: uuid.UUID) -> bool:
    return bool(
        (
            await db.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id}
            )
        ).scalar()
    )


async def test_no_chosen_policy_means_the_old_rows_stay(db: AsyncSession, tenant_ctx) -> None:
    await _clear_policy(db, tenant_ctx.tenant_id, MESSAGES)
    old = await _seed_message(db, tenant_ctx.tenant_id, body="old", age_days=900)

    result = await retention.purge_row_store(db, tenant_ctx.tenant_id, MESSAGES)
    assert result["skipped_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY
    assert result["deleted"] == 0
    assert await _exists(db, "messages", old)


async def test_a_chosen_horizon_deletes_exactly_the_rows_past_the_boundary(
    db: AsyncSession, tenant_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _clear_policy(db, tenant_ctx.tenant_id, MESSAGES)
    boundary = await _seed_message(db, tenant_ctx.tenant_id, body="b", age_days=400)
    old = await _seed_message(db, tenant_ctx.tenant_id, body="a", age_days=800)
    recent = await _seed_message(db, tenant_ctx.tenant_id, body="c", age_days=10)
    held = await _seed_message(
        db, tenant_ctx.tenant_id, body="d", age_days=800, status="unknown"
    )
    await retention.choose_policy(
        db, tenant_ctx.tenant_id, MESSAGES, retention_days=365, enabled=True
    )
    monkeypatch.setattr(retention, "ROW_PURGE_BATCH_SIZE", 1)
    monkeypatch.setattr(retention, "ROW_PURGE_MAX_BATCHES", 2)

    result = await retention.purge_row_store(db, tenant_ctx.tenant_id, MESSAGES)

    assert result["deleted"] == 2, result
    assert result["truncated"] is True  # the cap stopped it: two 1-row batches
    assert not await _exists(db, "messages", old)
    assert not await _exists(db, "messages", boundary)
    assert await _exists(db, "messages", recent)
    # §130: an 800-day-old message still awaiting reconciliation survives.
    assert await _exists(db, "messages", held)

    audits = (
        await db.execute(
            sa.text(
                "SELECT action, resource_id, after::text FROM audit_logs "
                "WHERE tenant_id = :t AND action = :a"
            ),
            {"t": str(tenant_ctx.tenant_id), "a": retention.ROW_PURGE_AUDIT_ACTION},
        )
    ).all()
    assert len(audits) == 1, audits
    assert audits[0][1] == MESSAGES
    assert "365" in audits[0][2]


async def test_a_paused_policy_purges_nothing_in_the_real_table(
    db: AsyncSession, tenant_ctx
) -> None:
    await _clear_policy(db, tenant_ctx.tenant_id, MESSAGES)
    old = await _seed_message(db, tenant_ctx.tenant_id, body="old", age_days=800)
    await retention.choose_policy(
        db, tenant_ctx.tenant_id, MESSAGES, retention_days=365, enabled=True
    )
    await db.execute(
        sa.text(
            "UPDATE retention_policies SET status = 'paused' "
            "WHERE tenant_id = :t AND data_class = :c"
        ),
        {"t": str(tenant_ctx.tenant_id), "c": MESSAGES},
    )
    await db.flush()

    result = await retention.purge_row_store(db, tenant_ctx.tenant_id, MESSAGES)
    assert result["skipped_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY
    assert await _exists(db, "messages", old)


async def test_ingress_rows_awaiting_human_hands_survive(db: AsyncSession, tenant_ctx) -> None:
    await _clear_policy(db, tenant_ctx.tenant_id, WEBHOOK_EVENTS)
    processed = await _seed_ingress_event(
        db, tenant_ctx.tenant_id, age_days=200, processing_status="processed"
    )
    dead = await _seed_ingress_event(
        db, tenant_ctx.tenant_id, age_days=200, processing_status="dead"
    )
    fresh = await _seed_ingress_event(
        db, tenant_ctx.tenant_id, age_days=1, processing_status="processed"
    )
    await retention.choose_policy(
        db, tenant_ctx.tenant_id, WEBHOOK_EVENTS, retention_days=90, enabled=True
    )

    result = await retention.purge_row_store(db, tenant_ctx.tenant_id, WEBHOOK_EVENTS)
    assert result["deleted"] == 1, result
    assert not await _exists(db, "webhook_events", processed)
    assert await _exists(db, "webhook_events", dead), "§24: dead awaits human hands"
    assert await _exists(db, "webhook_events", fresh)


async def test_another_tenants_rows_are_never_touched(
    db: AsyncSession, tenant_ctx
) -> None:
    """The tenant predicate is explicit, and RLS is the backstop — both must hold
    for a store whose tenant column is resolved at ingress rather than by FK.
    """
    from app.modules.identity.models import Tenant

    other = Tenant(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    db.add(other)
    await db.flush()
    # webhook_events is FORCE RLS, so even a neighbour's ingress row is written
    # with that tenant bound.
    await bind_tenant(db, other.id)
    other_row = await _seed_ingress_event(
        db, other.id, age_days=400, processing_status="processed"
    )
    await bind_tenant(db, tenant_ctx.tenant_id)

    await _clear_policy(db, tenant_ctx.tenant_id, WEBHOOK_EVENTS)
    mine = await _seed_ingress_event(
        db, tenant_ctx.tenant_id, age_days=400, processing_status="processed"
    )
    await retention.choose_policy(
        db, tenant_ctx.tenant_id, WEBHOOK_EVENTS, retention_days=90, enabled=True
    )

    result = await retention.purge_row_store(db, tenant_ctx.tenant_id, WEBHOOK_EVENTS)
    assert result["deleted"] >= 1
    assert not await _exists(db, "webhook_events", mine)

    await bind_tenant(db, other.id)
    assert await _exists(db, "webhook_events", other_row), "the sweep crossed tenants"
    await bind_tenant(db, tenant_ctx.tenant_id)


async def test_run_once_sweeps_every_row_store_a_tenant_chose(
    db: AsyncSession, tenant_ctx
) -> None:
    """The existing ``retention.run`` job is the wiring: no new job type, because
    a second purge job would be a second source of truth about the same rows.
    """
    for dc in (MESSAGES, WEBHOOK_EVENTS):
        await _clear_policy(db, tenant_ctx.tenant_id, dc)
        await retention.choose_policy(
            db, tenant_ctx.tenant_id, dc, retention_days=90, enabled=True
        )
    old_message = await _seed_message(db, tenant_ctx.tenant_id, body="gone", age_days=400)
    old_event = await _seed_ingress_event(
        db, tenant_ctx.tenant_id, age_days=400, processing_status="processed"
    )

    summary = await retention_worker.RetentionWorker.run_once(db, tenant_ctx.tenant_id)

    assert summary["skipped"] == [], summary
    assert summary["deleted"].get(MESSAGES, 0) >= 1
    assert summary["deleted"].get(WEBHOOK_EVENTS, 0) >= 1
    assert not await _exists(db, "messages", old_message)
    assert not await _exists(db, "webhook_events", old_event)


def test_the_row_purge_is_wired_into_a_job_that_is_already_seeded() -> None:
    """No third job type: the row sweep is the ``retention.run`` sweep the
    scheduler already seeds per active tenant, now gated.
    """
    from app.workers import scheduler_worker as sw

    assert "retention.run" in sw.RECURRING_JOBS
    assert "retention.run" in sw._HANDLERS
    handler_src = inspect.getsource(sw._handle_retention)
    assert "RetentionWorker.run_once" in handler_src
    assert "retention.purge_row_store" not in str(
        [name for name in sw.RECURRING_JOBS]
    ), "a row purge must not grow its own recurring job type"
