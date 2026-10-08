"""The agent-less AI-spend bucket must have a key the database can arbitrate.

``ai_usage`` is a ROLLUP: one row per (tenant, day, bucket). Its uniqueness is
declared by ``uq_ai_usage_tenant_period_agent UNIQUE (tenant_id, period_date,
agent_id)``, and ``app/modules/ai/usage.py`` writes it with a single
``INSERT ... ON CONFLICT (...) DO UPDATE`` so the row accumulates instead of
multiplying.

That design has a hole, and it is a PostgreSQL property rather than a coding
slip: a plain UNIQUE is ``NULLS NOT DISTINCT``-OFF, i.e. NULLs compare DISTINCT
(the SQL standard default, documented under ``CREATE INDEX``). So for a row whose
``agent_id`` IS NULL the conflict target can never match any stored row, the
``DO UPDATE`` branch is unreachable, and every agent-less write books a FRESH row
forever. Exactly one call site produces such a write: ``message_worker`` booking
inbound voice transcription, which is genuine platform spend — no agent has been
chosen yet at that point in the pipeline (``transcribe_inbound_voice`` runs
BEFORE ``maybe_auto_reply``, and the reply's agent is picked later, if at all).

The consequence is not lost money — every reader of ``ai_usage``
(``gateway._month_spend``/``_day_spend`` for the §42 cap, ``ai/router``'s usage
summary, ``billing``'s period snapshot) aggregates over
``tenant_id + period_date`` and never filters on ``agent_id``, so the sums stay
right. The damage is to the ledger's SHAPE: the rollup degenerates to one row per
call in a monthly partition that retention is supposed to bound, the dedupe the
constraint exists to provide is void for that bucket, and per-bucket attribution
becomes a row count rather than a row.

What this file pins, DB-free, is therefore a *shape* invariant with only one
legitimate way to satisfy it:

* the columns an upsert arbitrates on must be bound to non-NULL values, because
  a NULL in the arbiter is a row nothing will ever find again (test 1);
* the arbiter must be a real unique key of the table, and the insert must supply
  every column of it, and must never re-assign one in the UPDATE branch
  (tests 2-3);
* the bucket key must be STABLE — derived from the bucket, not a fresh uuid4 per
  call (test 4);
* the agent-less call site must STATE which bucket it books, so "forgot the
  kwarg" is a type error rather than a silent NULL (tests 5-6);
* and the model must describe the schema the migrations actually build, whose
  primary key became ``(id, period_date)`` when the table was partitioned
  (test 7).

What it deliberately does NOT do is weaken ``uq_ai_usage_tenant_period_agent``:
it is still there, still three columns, still plain-UNIQUE (test 8). NULLs being
distinct is the correct rule for "unknown agent" rows generally; what is wrong is
building an upsert whose ONLY arbiter relies on NULLs comparing equal.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import UniqueConstraint as sa_unique
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql

from app.modules.ai import usage as usage_module
from app.modules.ai.models import AIUsage
from app.modules.ai.usage import record_usage
from app.workers import message_worker

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
AGENT = uuid.UUID("33333333-3333-3333-3333-333333333333")
SPEND = Decimal("0.00375000")


class _CapturingSession:
    """Records the statement the recorder executed; nothing else."""

    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.statement = statement
        return SimpleNamespace()


def _compiled(statement):  # noqa: ANN001
    return statement.compile(dialect=postgresql.dialect())


def _sql_and_params(statement):  # noqa: ANN001
    compiled = _compiled(statement)
    return str(compiled), dict(compiled.params)


def _insert_columns(sql: str) -> list[str]:
    """The column list of `INSERT INTO ai_usage (a, b, ...) VALUES ...`."""
    match = re.search(r"INSERT INTO ai_usage \(([^)]*)\)", sql)
    assert match, f"no INSERT column list in: {sql}"
    return [c.strip() for c in match.group(1).split(",")]


def _arbiter_columns(sql: str) -> list[str]:
    """The inferred conflict target: `ON CONFLICT (a, b) DO UPDATE`."""
    match = re.search(r"ON CONFLICT \(([^)]*)\)\s+DO", sql, re.IGNORECASE)
    assert match, f"no ON CONFLICT target in: {sql}"
    return [c.strip() for c in match.group(1).split(",")]


def _set_columns(sql: str) -> list[str]:
    match = re.search(r"DO UPDATE SET (.*)$", sql, re.IGNORECASE | re.DOTALL)
    assert match, f"no DO UPDATE SET clause in: {sql}"
    return [term.split("=")[0].strip() for term in match.group(1).split(",")]


async def _book(**kwargs) -> tuple[str, dict]:  # noqa: ANN003
    session = _CapturingSession()
    await record_usage(session, TENANT, **kwargs)
    return _sql_and_params(session.statement)


async def _book_agentless() -> tuple[str, dict]:
    """The agent-less bucket, via whichever API the recorder currently offers.

    Resolved through the module rather than imported at the top so a missing
    sentinel fails the assertions below (the defect) instead of failing collection
    (an absence of evidence).
    """
    bucket = getattr(usage_module, "PLATFORM_BUCKET", None)
    if bucket is None:
        return await _book(cost=SPEND)
    return await _book(agent_id=bucket, cost=SPEND)


# ---------------------------------------------------------------------------
# 1. The defect: an arbiter column bound to NULL can never match a row
# ---------------------------------------------------------------------------


async def test_no_bucket_arbitrates_on_a_column_it_binds_null() -> None:
    """THE BUG. Every ON CONFLICT target column must be bound to a non-NULL value.

    A conflict is a match, a match is an equality test, and ``x = NULL`` is never
    true — which is why a plain UNIQUE (NULLS DISTINCT) cannot arbitrate the
    agent-less bucket. Binding NULL and still targeting that column does not raise
    and does not merge: it silently writes a new row on every call.
    """
    for label, (sql, params) in (
        ("agent bucket", await _book(agent_id=AGENT, cost=SPEND)),
        ("agent-less bucket", await _book_agentless()),
    ):
        arbiters = _arbiter_columns(sql)
        for column in arbiters:
            assert params.get(column) is not None, (
                f"{label} arbitrates on `{column}` while binding NULL for it: "
                "ON CONFLICT can never match a row whose arbiter column is NULL, "
                "so every write books a fresh ai_usage row instead of accumulating"
            )


async def test_the_agent_bucket_still_accumulates_on_the_natural_key() -> None:
    """The non-regression half: a real agent id keeps the existing arbiter.

    ``runtime.py`` books agent runs this way and it converges correctly — the fix
    must not disturb it, and must not spend its one conflict target on the PK.
    """
    sql, params = await _book(agent_id=AGENT, cost=SPEND)

    assert _arbiter_columns(sql) == ["tenant_id", "period_date", "agent_id"], sql
    assert params["agent_id"] == AGENT
    # Money stays Decimal in the port and in the increment (§47).
    assert params["cost"] == SPEND and params["cost_1"] == SPEND


# ---------------------------------------------------------------------------
# 2-3. Shape: target and insert must agree, and the target is a real key
# ---------------------------------------------------------------------------


def _unique_key_columns() -> set[tuple[str, ...]]:
    """Every unique key the model declares, as an ordered column-name tuple.

    `isinstance`, not `getattr(c, "unique", False)`: on a UniqueConstraint
    `unique` is a METHOD (`constraint.unique(column)`), and the boolean attribute
    belongs to `Index` — reading it loosely returns only the primary key and the
    pin silently degenerates to "the PK is a key".
    """
    table = AIUsage.__table__
    keys: set[tuple[str, ...]] = {tuple(c.name for c in table.primary_key.columns)}
    for constraint in table.constraints:
        if isinstance(constraint, sa_unique) and constraint.columns:
            keys.add(tuple(c.name for c in constraint.columns))
    return keys


async def test_the_conflict_target_is_a_declared_unique_key_of_the_table() -> None:
    """ON CONFLICT infers an arbiter from a unique index or it raises.

    Pinning the target against the model's keys is what catches the drift between
    "the recorder upserts on these columns" and "the schema stopped promising
    those columns are unique" — the class of change that turns an idempotent write
    into a ProgrammingError at 3am.
    """
    keys = _unique_key_columns()
    for label, (sql, _) in (
        ("agent bucket", await _book(agent_id=AGENT, cost=SPEND)),
        ("agent-less bucket", await _book_agentless()),
    ):
        target = tuple(_arbiter_columns(sql))
        assert target in keys, f"{label} arbitrates on {target}, not a unique key of {keys}"


async def test_every_arbiter_column_is_supplied_by_the_insert_and_never_reassigned() -> None:
    """The upsert's key must be an INPUT of the row, not something it mutates.

    Two separate failure modes this pins: a target column missing from the INSERT
    (the conflict can never be resolved against a value the row does not carry),
    and a target column in the SET list (a DO UPDATE that moves the row out of its
    own bucket, so the next write duplicates it — the same symptom as the NULL
    bug, arrived at from the other direction).
    """
    for label, (sql, _) in (
        ("agent bucket", await _book(agent_id=AGENT, cost=SPEND)),
        ("agent-less bucket", await _book_agentless()),
    ):
        inserted = _insert_columns(sql)
        arbiters = _arbiter_columns(sql)
        updated = _set_columns(sql)
        assert set(arbiters) <= set(inserted), f"{label}: arbiter not inserted: {arbiters}"
        assert not set(arbiters) & set(updated), (
            f"{label}: DO UPDATE re-assigns conflict column(s) "
            f"{sorted(set(arbiters) & set(updated))}"
        )


async def test_the_agent_less_bucket_key_is_stable_across_calls() -> None:
    """A bucket key derived per call is a fresh row per call, by construction.

    Re-booking the same tenant/day must produce byte-identical arbiter values,
    which rules out the tempting wrong fix (a new uuid4 so the FK is satisfied).
    """
    first_sql, first = await _book_agentless()
    second_sql, second = await _book_agentless()

    for column in _arbiter_columns(first_sql):
        assert first.get(column) == second.get(column), (
            f"bucket column `{column}` changed between two writes of the same "
            "bucket — the ledger cannot converge on a per-call key"
        )
    assert first_sql == second_sql


# ---------------------------------------------------------------------------
# 4-5. The bucket must be a decision, not an omitted keyword
# ---------------------------------------------------------------------------


def test_the_agent_less_bucket_is_a_named_sentinel_not_an_omitted_argument() -> None:
    """`agent_id` may not default to NULL, or "forgot it" stays invisible.

    The worker's call read `record_usage(session, tenant_id, cost=cost)` and the
    NULL that produced was indistinguishable from a deliberate one — that is how a
    rollup ends up with a row per voice note. A required keyword with an explicit
    sentinel makes the omission a TypeError at the call site and the agent-less
    case a thing a reader sees.
    """
    parameter = inspect.signature(record_usage).parameters["agent_id"]

    assert hasattr(usage_module, "PLATFORM_BUCKET"), (
        "no named bucket for genuinely agent-less spend: the recorder still reads "
        "an omitted agent_id as NULL, which its own conflict target cannot arbitrate"
    )
    assert parameter.default is inspect.Parameter.empty, (
        f"`agent_id` still defaults to {parameter.default!r} — the agent-less "
        "bucket must be stated, not left to a default"
    )


async def test_an_explicit_null_is_refused_rather_than_silently_bucketed() -> None:
    """A caller who WRITES `agent_id=None` is committing the original bug by hand.

    The type already forbids it, but the parameter is reached from untyped call
    sites and from `**kwargs` passthroughs, and the failure mode is silent row
    multiplication rather than an error — so the port refuses it out loud.
    """
    session = _CapturingSession()

    with pytest.raises(TypeError, match="PLATFORM_BUCKET"):
        await record_usage(session, TENANT, agent_id=None, cost=SPEND)

    assert session.statement is None, "a refused bucket must not have reached the database"


async def test_the_voice_worker_books_transcription_into_the_platform_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STT is platform spend, and the worker now has to say so.

    The transcript is produced BEFORE `maybe_auto_reply` picks an agent, and the
    money is spent even when no agent exists or the plan has no AI entitlement —
    so attributing it to an agent id would be a fiction (and the FK would demand a
    persisted `agents.id` whose deletion re-NULLs the column via ON DELETE SET
    NULL, re-opening this exact hole). The honest bucket is the agent-less one.
    """
    booked: list[dict] = []  # noqa: C401

    async def fake_reserve(session, tenant_id, *, estimated_cost=None, **kwargs):  # noqa: ANN001
        return uuid.uuid4()

    async def fake_settle(session, reservation_id):  # noqa: ANN001
        return None

    async def fake_record(session, tenant_id, **kwargs):  # noqa: ANN001
        booked.append(dict(kwargs))

    async def fake_transcribe(session, tenant_id, **kwargs):  # noqa: ANN001
        return SimpleNamespace(text="مرحبا", code=200)

    monkeypatch.setattr(message_worker, "reserve_budget", fake_reserve)
    monkeypatch.setattr(message_worker, "settle_reservation", fake_settle)
    monkeypatch.setattr(message_worker, "record_usage", fake_record)
    monkeypatch.setattr(message_worker, "stt_cost_estimate", lambda attachment: SPEND)
    monkeypatch.setattr(message_worker.VoiceService, "transcribe", staticmethod(fake_transcribe))

    attachment = SimpleNamespace(id=uuid.uuid4(), duration=45, transcription_status="pending")
    session = _VoiceNoteSession(attachment)
    text = await message_worker.transcribe_inbound_voice(session, TENANT, message_id=uuid.uuid4())

    assert text == "مرحبا"
    assert len(booked) == 1, booked
    assert booked[0].get("agent_id") is getattr(usage_module, "PLATFORM_BUCKET", "__missing__"), (
        "the worker left the bucket implicit: an omitted agent_id books a NULL-keyed "
        "row that the upsert can never accumulate into"
    )
    assert booked[0]["cost"] == SPEND, "money contract (§47) moved with the fix"


class _VoiceNoteSession:
    """The session surface ``transcribe_inbound_voice`` actually touches: the
    pending-attachment lookup, plus the commits its budget guard makes around
    reserve/settle/record (phase 2 of the worker opens no transaction itself).
    """

    def __init__(self, attachment) -> None:  # noqa: ANN001
        self._attachment = attachment

    async def execute(self, statement, params=None) -> SimpleNamespace:  # noqa: ANN001
        assert "FROM attachments" in str(statement), str(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: self._attachment)

    async def commit(self) -> None:
        return None


# ---------------------------------------------------------------------------
# 6. The model must describe the schema the migrations build
# ---------------------------------------------------------------------------


def test_the_model_declares_the_partitioned_primary_key() -> None:
    """``ai_usage``'s PK is ``(id, period_date)`` in the live schema, not ``(id)``.

    ``f7a2c9d4e8b1`` had to grow the key when it made the table a monthly RANGE
    partition ("insufficient columns in the PRIMARY KEY constraint definition"),
    and the model still says ``id`` alone. Anything that reasons about which unique
    key an upsert may target — including this file — reads the model, so the lie
    has to go: an arbiter that only exists in the database is unprovable here.
    """
    table = AIUsage.__table__

    assert [c.name for c in table.primary_key.columns] == ["id", "period_date"], (
        "the ORM's primary key disagrees with the partitioned table: the recorder "
        "cannot target a key the model does not declare"
    )
    assert not table.c.id.nullable and not table.c.period_date.nullable


# ---------------------------------------------------------------------------
# 7. Guard: this is not a licence to relax the constraint
# ---------------------------------------------------------------------------


def test_the_natural_key_is_unchanged_and_still_cannot_arbitrate_null() -> None:
    """The fix is in the writer, so the constraint must not move.

    ``uq_ai_usage_tenant_period_agent`` stays a plain three-column UNIQUE over
    ``(tenant_id, period_date, agent_id)`` with ``agent_id`` nullable. Making the
    NULL bucket converge by dropping the key, or by declaring it
    ``NULLS NOT DISTINCT``, would trade a working per-agent guarantee for a
    migration that redefines a constraint other code (and
    ``tests/test_ai_usage_partition_shape.py``) already reasons about. This
    assertion is the one that turns RED if someone "fixes" it there instead.
    """
    table = AIUsage.__table__
    natural = next(
        c
        for c in table.constraints
        if getattr(c, "name", None) == "uq_ai_usage_tenant_period_agent"
    )

    assert [c.name for c in natural.columns] == ["tenant_id", "period_date", "agent_id"]
    assert getattr(natural, "where", None) is None, "a partial UNIQUE is a schema change"
    assert table.c.agent_id.nullable, "the FK column stays nullable: agents can be deleted"
    assert table.c.agent_id.foreign_keys, "and it is still an FK, so no synthetic id fits it"


async def test_the_bucket_is_derived_from_tenant_day_and_agent_not_from_the_clock() -> None:
    """Two tenants, and two days, must never share a bucket row.

    The agent-less bucket is one row per tenant per day: if its key were derived
    from the day alone, tenant B would accumulate into tenant A's ledger row
    (RLS would refuse the write, but the key is still wrong), and if it were
    derived from the call rather than the period every call would still multiply.
    """
    derive = getattr(usage_module, "bucket_row_id", None)
    assert derive is not None, "no derivable bucket key: the ledger has no stable row id"

    today = date(2026, 9, 14)
    mine = derive(TENANT, today, None)
    assert isinstance(mine, uuid.UUID)
    assert mine == derive(TENANT, today, None), "the bucket id must be a function of the bucket"
    assert mine != derive(OTHER_TENANT, today, None), "cross-tenant bucket collision"
    assert mine != derive(TENANT, date(2026, 9, 15), None), "cross-day bucket collision"
    assert mine != derive(TENANT, today, AGENT), "the agent bucket is a different row"
    assert mine != derive(TENANT, today, uuid.UUID(int=0)), "bucket keys must be injective"


# ---------------------------------------------------------------------------
# 8. The live proof (CI only — needs the migrated schema)
# ---------------------------------------------------------------------------


async def test_agent_less_writes_converge_into_one_row_on_postgres(db, tenant_ctx) -> None:  # noqa: ANN001
    """The shape pins above, executed by the database that owns the semantics.

    Three agent-less bookings of the same tenant-day must land as ONE row with
    three model_calls. Without a non-NULL arbiter this asserts nothing less than
    three rows — and no number of compiled-SQL pins can prove that, because
    "NULLs are DISTINCT in a unique index" is a property of the index the write
    targets, not of the text of the INSERT. Skipped locally, green in CI.
    """
    from decimal import Decimal as D

    from app.modules.ai.usage import PLATFORM_BUCKET, bucket_row_id

    for _ in range(3):
        await record_usage(
            db, tenant_ctx.tenant_id, agent_id=PLATFORM_BUCKET, tokens_in=100, cost=D("0.001")
        )
    await db.flush()

    row = (
        await db.execute(
            sa_text(
                "SELECT count(*) AS n, sum(tokens_in) AS tokens, sum(model_calls) AS calls, "
                # `(array_agg(id ORDER BY id))[1]`, NOT `min(id)`: `ai_usage.id` is
                # a uuid and Postgres defines neither min(uuid) nor max(uuid), so
                # the audit died with "function min(uuid) does not exist" (CI run
                # 36136180924). This is the same aggregate and the same intent —
                # the id of the earliest row of the bucket's rows — in a spelling
                # Postgres can execute for any orderable type; pinned DB-free by
                # test_the_audit_aggregates_over_the_uuid_identity_are_postgres_legal.
                "sum(cost) AS cost, (array_agg(id ORDER BY id))[1] AS id FROM ai_usage "
                "WHERE tenant_id = :t AND agent_id IS NULL"
            ),
            {"t": tenant_ctx.tenant_id},
        )
    ).one()
    assert row.n == 1, f"the agent-less bucket fragmented into {row.n} rows"
    assert int(row.tokens) == 300 and int(row.calls) == 3
    assert row.cost == D("0.003"), row.cost
    # ...and it is the derived identity, so the next call finds it. The recorder
    # buckets by UTC (`gateway._month_spend` does too), so the expectation must
    # derive its day the same way rather than with a local `date.today()`.
    assert row.id == bucket_row_id(tenant_ctx.tenant_id, datetime.now(UTC).date(), None)

    # The natural key is still there, still plain, still three columns: the fix
    # moved the writer, not the promise.
    definition = (
        await db.execute(
            sa_text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'uq_ai_usage_tenant_period_agent'"
            )
        )
    ).scalar_one()
    assert "agent_id" in definition, definition
    assert "NULLS NOT DISTINCT" not in definition.upper(), (
        "the constraint was relaxed instead of the writer being fixed"
    )


async def test_the_agent_bucket_still_converges_on_the_natural_key(
    db,
    tenant_ctx,  # noqa: ANN001
) -> None:
    """The path that already worked must keep working on the same target.

    ``runtime.py`` books agent runs here; this is the regression guard against the
    platform bucket's new identity leaking into the per-agent key (which would
    make two agents of one tenant/day fight over one row).
    """
    from decimal import Decimal as D

    from app.modules.ai.models import Agent

    first = Agent(tenant_id=tenant_ctx.tenant_id, name="Bucket A", model="fast")
    second = Agent(tenant_id=tenant_ctx.tenant_id, name="Bucket B", model="fast")
    db.add_all([first, second])
    await db.flush()

    for agent in (first, second, first):
        await record_usage(db, tenant_ctx.tenant_id, agent_id=agent.id, cost=D("0.25"))
    await db.flush()

    rows = (
        await db.execute(
            sa_text(
                "SELECT agent_id, count(*) AS n, sum(cost) AS cost, sum(model_calls) AS calls "
                "FROM ai_usage WHERE tenant_id = :t AND agent_id IS NOT NULL GROUP BY agent_id"
            ),
            {"t": tenant_ctx.tenant_id},
        )
    ).all()
    assert len(rows) == 2, rows
    assert {int(r.calls) for r in rows} == {1, 2}, rows
    assert all(r.cost == D("0.25") or r.cost == D("0.50") for r in rows), rows


# ---------------------------------------------------------------------------
# 9. The audit SQL itself must be Postgres-legal over the uuid identity
# ---------------------------------------------------------------------------


def _sql_statements_of_this_module() -> list[str]:
    """Every SQL text this module hands to `sa_text(...)`, captured DB-free.

    The statements are written as implicit string concatenations, and
    `ast.literal_eval` folds those into exactly the text the database would
    receive — the capture a recording session would make, with no database to
    record from (this file's statements only run against Postgres, which is the
    one thing the DB-free pins cannot assume).
    """
    tree = ast.parse(inspect.getsource(sys.modules[__name__]))
    return [
        ast.literal_eval(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "sa_text" and node.args
    ]


_UUID_IDENTITY_AGGREGATE = re.compile(r"\b(?:min|max)\s*\(\s*id\s*\)", re.IGNORECASE)


def test_the_audit_aggregates_over_the_uuid_identity_are_postgres_legal() -> None:
    """`ai_usage.id` is a uuid, and Postgres has NO `min(uuid)` / `max(uuid)`.

    The agent-less audit is a production-shaped aggregate: count/sum the bucket's
    rows and return the identity of the earliest of them, so the caller can pin
    that row to the derived bucket key. Its first spelling reached for `min(id)` —
    but Postgres refuses the aggregate over a uuid outright ("function min(uuid)
    does not exist", CI run 36136180924), which is the exact statement a
    production audit of the platform bucket would die on. The intent survives in
    a legal spelling: `(array_agg(id ORDER BY id))[1]` IS the earliest id of the
    aggregated set, for any type Postgres can order. The live proof cannot run
    without Postgres, so the shape is pinned where no database is needed: the
    statements this file issues must aggregate the uuid identity legally, and
    BOTH branches must stay symmetric — the agent-less audit via the array
    spelling, its agent-scoped sibling via the GROUP BY key, never a min/max.
    """
    audits = [s for s in _sql_statements_of_this_module() if "FROM ai_usage" in s]

    agentless = [s for s in audits if "agent_id IS NULL" in s]
    assert agentless, f"the agent-less audit statement went missing: {audits}"
    for sql in agentless:
        assert "AS id" in sql, sql
        assert not _UUID_IDENTITY_AGGREGATE.search(sql), (
            f"min/max over the uuid identity is `function min(uuid) does not "
            f"exist` on Postgres 17; the earliest row of the set is spelled "
            f"`(array_agg(id ORDER BY id))[1]`: {sql}"
        )
        assert "(array_agg(id ORDER BY id))[1]" in sql, sql

    agent_scoped = [s for s in audits if "agent_id IS NOT NULL" in s]
    assert agent_scoped, f"the agent-scoped sibling audit went missing: {audits}"
    for sql in agent_scoped:
        assert "GROUP BY agent_id" in sql, sql
        assert not _UUID_IDENTITY_AGGREGATE.search(sql), sql
