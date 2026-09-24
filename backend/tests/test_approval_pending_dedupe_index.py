"""§135 — the PENDING dedupe in ``ApprovalService.request`` is a DATABASE rule.

The defect (found while fixing a different bug; verified against
``app/modules/ai/approvals.py``): ``request`` dedupes an existing PENDING
approval with an UNLOCKED check-then-act — SELECT for a PENDING row, INSERT if
none. Under concurrency two simultaneous gate entries for the same
(tenant, conversation, action, payload_hash) each see no PENDING row and both
INSERT, so a reviewer is asked to approve the same HIGH-risk action twice and
BOTH grants can then be consumed by different executions (``find_granted``
serialises consumption — this file does not re-litigate that; the CREATION side
was the hole). No amount of application checking fixes a check-then-act; the
rule belongs in the index layer.

The index must express EXACTLY what ``request`` compares
(``approvals.py`` dedupe SELECT):

* ``tenant_id``, ``conversation_id``, ``action``, ``payload_hash`` — all four,
  and ``payload_hash`` IS part of the key (G-02 bound approvals to arguments);
* restricted to ``status = 'PENDING'`` — decided rows must stay append-only
  history;
* ``conversation_id`` is NULLABLE and the service's ``==`` against ``None``
  renders ``IS NULL``, i.e. the service DOES dedupe the no-conversation case.
  Postgres treats NULLs as DISTINCT in a UNIQUE index, so a bare
  ``conversation_id`` column would silently fail to dedupe exactly the rows
  the service intends to collapse. The key therefore buckets NULL through
  ``coalesce(conversation_id, '<nil uuid>'::uuid)``. The nil UUID cannot
  collide: it is never generated as a conversation id by any code path.

Rows with a NULL ``payload_hash`` (pre-``a2b3c4d5e6f7`` legacy approvals) stay
DISTINCT in the index — which is right, not an oversight: the service's
``payload_hash = :fingerprint`` never matches a NULL row either, so legacy
pending rows fail closed and need a fresh decision. Both sides keep NULLs
distinct; neither side pretends to dedupe what its predicate cannot see.

Convergence idiom (``test_snapshot_truncate_freeze.py`` precedent): the index
statement is spelled ONCE below, the migration must emit exactly that string
after whitespace normalisation, and the service's compiled dedupe SELECT is
parsed for the same column set and the same ``'PENDING'`` literal — so
service, index, and test cannot drift apart on any runner.

ON CONFLICT: none exists for ``approval_requests`` anywhere in ``app`` (the
partial index would force re-spelling the WHERE clause in the inference
target; ``request`` uses a savepoint + re-read instead).
``test_no_on_conflict_statement_targets_approval_requests`` pins that fact.

The real concurrency proof is the DB-gated gate test in
``tests/gate/test_gate_approval_duplicate_pending.py`` — CI-only.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.ai.approvals import ApprovalService, payload_fingerprint
from app.modules.ai.models import ApprovalRequest

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    BACKEND
    / "migrations"
    / "versions"
    / "e6f7a8b9c0d1_approval_pending_dedupe_index.py"
)

#: The head this revision must extend. An applied revision is immutable, so a
#: new rule arrives as a NEW file whose down_revision is today's head.
CURRENT_HEAD = "f3b7d9c1a5e8"

TABLE = "approval_requests"
INDEX_NAME = "uq_approvals_pending_dedupe"
#: The bucket for conversation_id IS NULL — see module docstring.
NIL_UUID = "00000000-0000-0000-0000-000000000000"

#: The dedup key, spelled ONCE. The migration emits exactly this; the
#: service's SELECT is checked to compare exactly these columns.
DEDUPE_COLUMNS = ("tenant_id", "conversation_id", "action", "payload_hash")
CONVERSATION_BUCKET_SQL = f"coalesce(conversation_id, '{NIL_UUID}'::uuid)"
PENDING_PREDICATE_SQL = "status = 'PENDING'"
EXPECTED_INDEX_SQL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} ON {TABLE} ("
    f"tenant_id, {CONVERSATION_BUCKET_SQL}, action, payload_hash) "
    f"WHERE {PENDING_PREDICATE_SQL}"
)

ACTION = "gate.purge_customer_data"
ARGUMENTS = {"arguments": {"customer_id": "c-1", "note": "dedupe"}}


# ------------------------------------------------ the migration (DB-free) --


class _RecordingOp:
    """Permissive Alembic `op` stand-in: records execute(), no-ops the rest."""

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def execute(self, sql, *args, **kwargs) -> None:  # noqa: ANN001, ANN002, ANN003
        if isinstance(sql, str):
            self._captured.append(sql)

    def __getattr__(self, name: str):  # noqa: ANN204
        return lambda *a, **k: None


def _load_migration() -> tuple[object, list[str]]:
    captured: list[str] = []
    spec = importlib.util.spec_from_file_location(
        "approval_pending_dedupe_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = _RecordingOp(captured)  # type: ignore[attr-defined]
    return module, captured


def _normalise(sql: str) -> str:
    """Collapse whitespace; comment lines are the migration's voice, not SQL.

    Pretty-printed DDL puts a newline after `(` and before `)`; that is
    formatting, not definition, so the comparison is on paren-adjacent
    whitespace stripped.
    """
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    joined = " ".join(" ".join(lines).split())
    return joined.replace("( ", "(").replace(" )", ")")


def _upgraded_statements() -> list[str]:
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    return [_normalise(sql) for sql in captured]


def test_the_revision_descends_from_the_current_head() -> None:
    """`alembic upgrade head` branches — and the deploy stops — on a wrong parent."""
    module, _ = _load_migration()
    assert module.revision != CURRENT_HEAD
    assert module.down_revision == CURRENT_HEAD


def test_the_index_is_the_exact_statement_spelled_in_this_file() -> None:
    """The convergence half: the migration emits ONE string, pinned here.

    Not a paraphrase and not a regex near-miss — after whitespace
    normalisation the emitted CREATE UNIQUE INDEX must equal the expected
    statement character for character. UNIQUE + partial + the coalesce bucket
    are all load-bearing (see module docstring).
    """
    statements = _upgraded_statements()
    index_statements = [s for s in statements if "CREATE UNIQUE INDEX" in s.upper()]
    assert len(index_statements) == 1, f"expected one index, got {index_statements}"
    assert index_statements[0] == EXPECTED_INDEX_SQL


def test_duplicates_are_collapsed_before_the_index_is_built() -> None:
    """A UNIQUE index on a table that already has duplicate PENDING rows aborts
    `alembic upgrade head` — the deploy IS the first place this rule meets real
    data. The collapse must (a) exist, (b) mirror the index key exactly
    (coalesce bucket, PENDING on BOTH sides, payload_hash equality), and (c)
    run BEFORE the index statement.
    """
    statements = _upgraded_statements()
    deletes = [s for s in statements if re.match(r"DELETE FROM approval_requests\b", s)]
    assert len(deletes) == 1, f"expected one collapse DELETE, got {deletes}"
    delete = deletes[0]
    index_at = next(i for i, s in enumerate(statements) if "CREATE UNIQUE INDEX" in s.upper())
    delete_at = next(i for i, s in enumerate(statements) if s in deletes)
    assert delete_at < index_at, "the collapse DELETE must run before the CREATE UNIQUE INDEX"
    for fragment in (
        "a.id < b.id",
        f"coalesce(a.conversation_id, '{NIL_UUID}'::uuid)",
        f"coalesce(b.conversation_id, '{NIL_UUID}'::uuid)",
        "a.tenant_id = b.tenant_id",
        "a.action = b.action",
        "a.payload_hash = b.payload_hash",
    ):
        assert fragment in delete, f"collapse DELETE does not mirror the index key: {fragment}"
    assert delete.count(PENDING_PREDICATE_SQL) == 2, (
        "both sides must be PENDING — collapsing decided history is data loss"
    )


def test_the_downgrade_drops_only_the_index() -> None:
    """Rollback is a rollback: the rule goes away, no row does.

    Also the shape `test_migrations.test_every_dropped_index_was_created`
    checks for the hardening migration: nothing is dropped that was not made.
    """
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    after_upgrade = len(captured)
    module.downgrade()  # type: ignore[attr-defined]
    down = [_normalise(sql) for sql in captured[after_upgrade:]]
    assert down == [f"DROP INDEX IF EXISTS {INDEX_NAME}"]


def test_the_migration_sql_parses_as_postgresql() -> None:
    """Offline syntax proof: a malformed statement fails the deploy, not a test."""
    pglast = pytest.importorskip("pglast", reason="pglast is a dev-only parser")
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    module.downgrade()  # type: ignore[attr-defined]
    for sql in captured:
        pglast.parser.parse_sql(sql)


# ------------------------------ the service SELECT vs the index (no drift) --


def _pg(statement) -> str:  # noqa: ANN001
    from sqlalchemy.dialects import postgresql

    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class _StubResult:
    def __init__(self, row=None):  # noqa: ANN001
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Savepoint:
    def __init__(self, session: _StubSession) -> None:
        self._session = session

    async def __aenter__(self) -> _Savepoint:
        self._session.nested_entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        if exc_type is not None:
            self._session.nested_rolled_back += 1
        return False  # propagate — real SQLAlchemy rolls back and re-raises too


class _StubSession:
    """Records statements; feeds canned SELECT answers; can fail the flush."""

    def __init__(self, select_rows: list, flush_error: Exception | None = None) -> None:
        self.statements: list = []
        self.added: list = []
        self.nested_entered = 0
        self.nested_rolled_back = 0
        self.flushed = 0
        self._select_rows = list(select_rows)
        self._flush_error = flush_error

    async def execute(self, statement, params=None):  # noqa: ANN001, ANN002
        self.statements.append(statement)
        return _StubResult(self._select_rows.pop(0))

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self)

    async def flush(self) -> None:
        self.flushed += 1
        if self._flush_error is not None:
            error, self._flush_error = self._flush_error, None
            raise error


async def _call_request(session: _StubSession, *, conversation_id) -> ApprovalRequest:
    return await ApprovalService.request(
        session,
        uuid.uuid4(),
        run_id=None,
        conversation_id=conversation_id,
        entity_type="tool",
        entity_id=ACTION,
        action=ACTION,
        payload=ARGUMENTS,
    )


async def test_the_service_dedupe_select_uses_the_index_key_verbatim() -> None:
    """The other convergence half: parse the SELECT the service actually runs.

    Extract the equality-compared columns and the status literal from the
    compiled dedupe SELECT and require exactly DEDUPE_COLUMNS and
    PENDING_PREDICATE_SQL. If either side drifts — the service stops comparing
    payload_hash, or the index loses the bucket — one of the two convergence
    tests here goes red.
    """
    session = _StubSession([None, None])
    await _call_request(session, conversation_id=uuid.uuid4())
    assert session.statements, "request never consulted the database"
    sql = _pg(session.statements[0])
    compared = set(re.findall(r"approval_requests\.(\w+) = ", sql))
    assert compared == set(DEDUPE_COLUMNS) | {"status"}, sql
    assert PENDING_PREDICATE_SQL in sql, sql
    assert f"payload_hash = '{payload_fingerprint(ARGUMENTS)}'" in sql, (
        "the index dedupes on the fingerprint; the SELECT must too"
    )


async def test_a_null_conversation_still_reaches_the_bucketed_index() -> None:
    """The service dedupes IS-NULL conversations (== None renders IS NULL), so
    the index must bucket them or the rule silently misses those rows. This
    pins the service side of that pair; the exact-string pin above holds the
    coalesce in the index.
    """
    session = _StubSession([None, None])
    await _call_request(session, conversation_id=None)
    sql = _pg(session.statements[0])
    assert "conversation_id IS NULL" in sql, sql


# --------------------------- the constraint violation is the idempotent answer


class _DrvError(Exception):
    """Stands in for asyncpg's DuplicateTableError etc. — only pgcode matters."""

    def __init__(self, pgcode: str) -> None:
        super().__init__(f"pgcode={pgcode}")
        self.pgcode = pgcode


def _integrity(pgcode: str) -> IntegrityError:
    return IntegrityError(
        "INSERT INTO approval_requests DEFAULT VALUES", {}, _DrvError(pgcode)
    )


async def test_duplicate_pending_key_returns_the_winner_not_a_500() -> None:
    """THE behavior change: the pre-check saw nothing, the INSERT lost the
    race to uq_approvals_pending_dedupe (23505), and `request` must turn that
    into the same idempotent answer the pre-check intended — the existing row.
    """
    tenant_id = uuid.uuid4()
    winner = ApprovalRequest(
        tenant_id=tenant_id,
        conversation_id=uuid.uuid4(),
        action=ACTION,
        entity_type="tool",
        entity_id=ACTION,
        payload=ARGUMENTS,
        payload_hash=payload_fingerprint(ARGUMENTS),
        status="PENDING",
    )
    session = _StubSession([None, winner], flush_error=_integrity("23505"))
    result = await ApprovalService.request(
        session,
        tenant_id,
        run_id=None,
        conversation_id=winner.conversation_id,
        entity_type="tool",
        entity_id=ACTION,
        action=ACTION,
        payload=ARGUMENTS,
    )
    assert result is winner
    # The INSERT was wrapped in a savepoint, and the violation rolled back to
    # it — without that the outer transaction would be aborted and the
    # re-read below would raise instead of answering.
    assert session.nested_entered == 1, "the INSERT is not savepoint-wrapped"
    assert session.nested_rolled_back == 1, "the savepoint did not roll back the failed INSERT"
    # The loser's row must not remain queued for flush in the outer transaction.
    assert len(session.statements) == 2
    assert _pg(session.statements[0]) == _pg(session.statements[1]), (
        "the post-violation re-read must be the SAME dedupe statement as the "
        "pre-check — one SQL string, spelled once"
    )


async def test_a_non_unique_integrity_error_is_not_swallowed() -> None:
    """23505 means 'someone else made this pending request'. 23503 (FK) means
    a broken row — converting it to an idempotent success would hide a real
    defect, so it must propagate.
    """
    session = _StubSession([None], flush_error=_integrity("23503"))
    with pytest.raises(IntegrityError):
        await _call_request(session, conversation_id=uuid.uuid4())
    assert session.nested_rolled_back == 1


async def test_23505_without_a_visible_winner_still_raises() -> None:
    """Fail closed: if the re-read finds nothing the violation came from
    something this rule cannot explain (e.g. a concurrent decision moved the
    row out of PENDING between INSERT-failure and re-read). Returning None or
    inventing a row would be worse than surfacing the error.
    """
    session = _StubSession([None, None], flush_error=_integrity("23505"))
    with pytest.raises(IntegrityError):
        await _call_request(session, conversation_id=uuid.uuid4())


# ---------------------------------------------------------- ON CONFLICT rule --


def test_no_on_conflict_statement_targets_approval_requests() -> None:
    """A partial unique index requires the WHERE clause to be REPEATED in the
    ON CONFLICT inference target; spell it wrong and Postgres raises
    "there is no unique or matching constraint" at runtime. Rather than
    scatter that footgun, `request` handles the violation with a savepoint +
    re-read, and this pins that no code writes these rows with ON CONFLICT.
    """
    offenders: list[str] = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "on_conflict" not in source.lower():
            continue
        if "ApprovalRequest" in source or "approval_requests" in source:
            offenders.append(str(path.relative_to(BACKEND)))
    assert not offenders, (
        "ON CONFLICT meets approval_requests in a file that writes them — a "
        "partial-index inference target must re-spell WHERE status = 'PENDING' "
        f"(and the bucket coalesce): {offenders}"
    )
