"""§137 — the inbox READ MODEL.

Spec §137 (``ARCHITECTURE_PATCH_125-177.txt``, "# §137 — CROSS-MODULE READ
LAYER", lines 724-795) is the rule this file enforces. In its own words the
rule is:

    No cross-module repository access            (stays true, line 729)
    but a  Read / Query Layer  is allowed, reading from
        public read contracts / read models / approved DB views / analytics
    Example Inbox (lines 749-759):
        Conversation + Customer + Last Message + Assignment
    must NOT happen via  ConversationRepository -> CustomerRepository
    but via  InboxQuery   "أو read model"  (lines 768-774)

So §137 names the seam exactly — ``InboxQuery`` — and offers a read model as
the alternative spelling of the same thing. It does **not** demand a
materialized projection table: "أو read model" is an option, and the
Consistency paragraph (lines 776-794) is about accepting that a projection
lags ("لا نفترض أن كل read model immediately consistent"). A lagging
projection would then need §137's own escape hatch — an "authoritative read"
for the critical read-after-write case — which this design does not need,
because it reads the live tables and is therefore immediately consistent by
construction.

What that leaves as the measurable contract, and what this file pins:

1. ONE inbox page — Conversation + Customer + Last Message + Assignment +
   unread + SLA — answered in a BOUNDED number of statements (§110,
   ``ARCHITECTURE_SPEC_1-124.txt`` line 3624 "No N+1"), that count not growing
   with the page size.
2. Filters, sort and the keyset cursor pushed INTO SQL: §99's "My Inbox" and
   "Unassigned" views are assignee filters, so the list needs
   ``WHERE assignee_user_id = :me`` / ``IS NULL``, not a browser filter over
   whatever page arrived.
3. The read is NOT performed by the write service — which is exactly what
   ``docs/GAP_REGISTER.md`` §4 records as "absent (joins in write service)".

WHAT WAS ACTUALLY HERE BEFORE (measured, not estimated, with the recording
session below):

* ``ConversationService.list_inbox`` (the only working list, served at
  ``GET /conversations``): **2 statements** per page at any page size, and it
  answers Conversation + Customer + Assignment only — no Last Message, no SLA.
  It also reached into ``customers`` by importing ``CustomerService`` (the
  ``ConversationRepository -> CustomerRepository`` shape §137 forbids) and
  bolted ``customer_name``/``customer_phone`` onto ORM instances, which is a
  read model pretending to be an entity.
* ``GET /sla/risk`` to supply the missing SLA: **2 more statements**, over
  every running/breached SLA in the tenant rather than the conversations on
  the page — so a complete §137 inbox page cost **4 statements across 2 HTTP
  round trips**, joined in the browser (``frontend/src/lib/queries.ts`` §99
  comment, lines 628-645).
* ``ConversationService.inbox_query`` — the thing that CLAIMED to be the §137
  read model — was **1 statement that cannot execute**: it selected
  ``c.last_message_preview``, ``c.sla_status`` and ``c.sla_deadline_at`` from
  ``conversations``, and no such column exists in the model or in any
  migration. ``test_column_guard_catches_an_invented_column`` is the guard
  that catches that class of bug without a database, which matters because
  every DB-backed test skips locally and the endpoint had no test at all.

AFTER: 1 statement, 1 round trip. See ``test_one_inbox_page_is_one_statement``
and ``test_the_statement_count_does_not_grow_with_the_page_size``.

DATABASE_URL_APP_ADMIN note: the statement-count, SQL-shape, column-existence
and PII tests below are DB-free and run anywhere. The five tests that EXECUTE
the SQL — ``test_page_reports_the_inbox_elements_from_live_rows``,
``test_unread_cannot_drift_from_the_facts_it_projects``,
``test_page_is_tenant_isolated``,
``test_one_page_costs_one_statement_on_a_real_database``,
``test_preview_is_bounded_in_sql`` — SKIP locally and are CI-only claims, as is
the new index migration applying cleanly.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.db import Base
from app.modules.conversations.inbox import INBOX_PREVIEW_CHARS, InboxQuery

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION = uuid.UUID("33333333-3333-3333-3333-333333333333")
CUSTOMER = uuid.UUID("44444444-4444-4444-4444-444444444444")
ASSIGNEE = uuid.UUID("55555555-5555-5555-5555-555555555555")
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


# ------------------------------------------------- the recording session ---


class _Rows:
    """Whatever ``execute`` was told to hand back, in every fetch shape."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _Rows:
        return self

    def mappings(self) -> _Rows:
        return self

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self) -> int:
        return len(self._rows)


class RecordingSession:
    """Counts statements without a database.

    ``before_cursor_execute`` (the SQLAlchemy event the CI-only counter uses)
    needs a real connection; this counts the statements the code ISSUES, which
    is the quantity under test. A page that stops at one ``execute()`` costs
    one statement wherever it runs.
    """

    def __init__(self, rows: list[object] | None = None) -> None:
        self.statements: list[tuple[str, dict | None]] = []
        self._rows = rows or []

    async def execute(self, stmt: object, params: dict | None = None, *a: object, **k: object):
        self.statements.append((" ".join(str(stmt).split()), params))
        return _Rows(self._rows)

    def add(self, *a: object) -> None:
        raise AssertionError("the §137 read layer must never write")

    async def flush(self) -> None:  # pragma: no cover - guarded by add()
        raise AssertionError("the §137 read layer must never write")


def _row(**columns: object) -> SimpleNamespace:
    """A ``text()`` result row; un-named columns read as None.

    The default matters: it lets these tests assert the CONTRACT (which keys
    the page answers) without restating the row expression, so adding a column
    to the read model cannot be hidden by a fixture that happens to match it.
    """

    class _R(SimpleNamespace):
        def __getattr__(self, name: str) -> None:
            return None

    return _R(**columns)


def _sample_row() -> SimpleNamespace:
    return _row(
        id=CONVERSATION,
        status="open",
        channel="whatsapp",
        customer_id=CUSTOMER,
        customer_name="منى",
        customer_phone="+201000000000",
        assignee_user_id=ASSIGNEE,
        created_at=NOW,
        last_message_at=NOW,
        last_customer_message_at=NOW,
        messaging_policy_state="open",
        unread_count=3,
        last_message_preview="هل السعر نهائي؟",
        last_message_content_type="text",
        last_message_direction="inbound",
        last_message_sender_type="customer",
        sla_kind="first_response",
        sla_status="running",
        sla_deadline_at=NOW + timedelta(minutes=30),
    )


# ------------------------------------------------ the elements of §137 ----


async def test_one_inbox_page_is_one_statement() -> None:
    session = RecordingSession([_sample_row()])
    page = await InboxQuery.page(session, TENANT, limit=50, now=NOW)
    assert len(session.statements) == 1, (
        f"a §137 inbox page must cost one statement; it cost {len(session.statements)}: "
        f"{[sql[:70] for sql, _ in session.statements]}"
    )
    assert len(page) == 1


async def test_the_statement_count_does_not_grow_with_the_page_size() -> None:
    """§110 "No N+1": one page is one statement whether it holds 1 or 200 rows."""
    for size in (1, 10, 50, 200):
        rows = [_sample_row() for _ in range(size)]
        session = RecordingSession(rows)
        page = await InboxQuery.page(session, TENANT, limit=size)
        assert len(page) == size
        assert len(session.statements) == 1, f"page size {size} cost {len(session.statements)}"


async def test_page_answers_every_element_137_names() -> None:
    """Conversation + Customer + Last Message + Assignment, from one read."""
    session = RecordingSession([_sample_row()])
    item = (await InboxQuery.page(session, TENANT, limit=50, now=NOW))[0]

    # Conversation
    assert item["id"] == str(CONVERSATION)
    assert item["status"] == "open"
    assert item["channel"] == "whatsapp"
    # unread — the column the write path owns, projected not recomputed
    assert item["unread_count"] == 3
    # Customer
    assert item["customer_id"] == str(CUSTOMER)
    assert item["customer_name"] == "منى"
    # Last Message — the element /conversations could not answer at all
    assert item["last_message_preview"] == "هل السعر نهائي؟"
    assert item["last_message_direction"] == "inbound"
    assert item["last_message_content_type"] == "text"
    # Assignment
    assert item["assignee_user_id"] == str(ASSIGNEE)
    # SLA — previously only reachable via a second request to /sla/risk
    assert item["sla_status"] == "running"
    assert item["sla_deadline_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert item["sla_minutes_remaining"] == 30


async def test_a_conversation_with_no_messages_still_pages() -> None:
    """A brand-new conversation has no message and no SLA row: NULLS LAST, not missing."""
    session = RecordingSession(
        [
            _row(
                id=CONVERSATION,
                status="open",
                channel="webchat",
                customer_id=CUSTOMER,
                created_at=NOW,
                unread_count=0,
            )
        ]
    )
    item = (await InboxQuery.page(session, TENANT, limit=50))[0]
    assert item["last_message_preview"] is None
    assert item["last_message_at"] is None
    assert item["sla_status"] is None
    assert item["sla_deadline_at"] is None
    assert item["unread_count"] == 0


# --------------------------------------- filters / sort / paging in SQL ---


async def test_assignee_and_status_filters_are_pushed_into_sql() -> None:
    """>99 "My Inbox" / "Unassigned" must be SQL predicates, not browser filters.

    Before this change ``GET /conversations`` had no assignee parameter at all
    and the frontend filtered the loaded pages client-side
    (``INBOX_CLIENT_VIEWS`` in ``frontend/src/lib/queries.ts``).
    """
    session = RecordingSession([])
    await InboxQuery.page(session, TENANT, status="open", assignee_user_id=ASSIGNEE, limit=50)
    sql, params = session.statements[0]
    assert "c.status = :status" in sql
    assert "assignee_user_id = :assignee_user_id" in sql
    assert params is not None
    assert params["status"] == "open"
    assert str(params["assignee_user_id"]) == str(ASSIGNEE)


async def test_unassigned_is_an_is_null_predicate() -> None:
    session = RecordingSession([])
    await InboxQuery.page(session, TENANT, unassigned=True, limit=50)
    sql, params = session.statements[0]
    assert "assignee_user_id IS NULL" in sql
    assert params is not None
    assert "assignee_user_id" not in params


async def test_assigned_to_anyone_is_not_sentinel_confused_with_unassigned() -> None:
    """``assignee_user_id=_UNASSIGNED`` and a real id cannot both apply."""
    session = RecordingSession([])
    await InboxQuery.page(session, TENANT, assignee_user_id=ASSIGNEE, unassigned=True, limit=50)
    sql, _ = session.statements[0]
    assert "assignee_user_id IS NULL" in sql
    assert "assignee_user_id = :assignee_user_id" not in sql


async def test_sort_and_keyset_cursor_live_in_sql() -> None:
    session = RecordingSession([])
    await InboxQuery.page(session, TENANT, limit=50, before_at=NOW, before_id=CONVERSATION)
    sql, params = session.statements[0]
    assert "ORDER BY" in sql
    assert "NULLS LAST" in sql, "last_message_at is nullable; the sort must be total"
    assert params is not None
    assert "before_at" in params and "before_id" in params
    # The keyset must survive the NULL tail of the ordering, or the last page
    # of a list containing an unanswered conversation is unreachable.
    assert re.search(r"last_message_at IS NULL", sql), "NULL tail of the keyset unhandled"


async def test_a_cursor_into_the_null_tail_narrows_by_id() -> None:
    """A tail cursor must exclude dated rows and shrink by id.

    This is the case a sentinel instant would get wrong in both directions:
    ``before_at`` NULL means "everything dated has already been shown", so
    re-emitting the dated branch repeats earlier pages, and re-emitting the
    whole tail never advances at all.
    """
    session = RecordingSession([])
    await InboxQuery.page(session, TENANT, limit=50, before_at=None, before_id=CONVERSATION)
    sql, params = session.statements[0]
    assert params is not None
    assert params["before_at"] is None
    assert "c.last_message_at IS NULL" in sql
    assert "c.id < CAST(:before_id AS uuid)" in sql


def test_keyset_cursor_round_trips_a_null_instant() -> None:
    from app.modules.conversations.inbox import decode_keyset, encode_keyset

    assert decode_keyset(encode_keyset(None, CONVERSATION)) == (None, CONVERSATION)
    assert decode_keyset(encode_keyset(NOW, CONVERSATION)) == (NOW, CONVERSATION)


def test_keyset_cursor_still_accepts_the_shape_it_shipped_with() -> None:
    """/conversations issued ``created_at`` cursors before this read model.

    A deploy must not turn every in-flight cursor into a 400 that a client
    cannot tell apart from a corrupt token, so the legacy key still decodes.
    """
    import base64
    import json

    from app.core.pagination import decode_cursor
    from app.modules.conversations.inbox import decode_keyset

    legacy = (
        base64.urlsafe_b64encode(
            json.dumps({"created_at": NOW.isoformat(), "id": str(CONVERSATION)}).encode()
        )
        .decode()
        .rstrip("=")
    )
    assert decode_keyset(legacy) == decode_cursor(legacy)


def test_keyset_cursor_rejects_garbage_as_the_other_lists_do() -> None:
    from app.core.errors import InvalidCursorError
    from app.modules.conversations.inbox import decode_keyset

    with pytest.raises(InvalidCursorError):
        decode_keyset("not-a-cursor")


async def test_limit_reaches_sql_instead_of_slicing_in_python() -> None:
    rows = [_sample_row() for _ in range(120)]
    session = RecordingSession(rows)
    page = await InboxQuery.page(session, TENANT, limit=50)
    sql, params = session.statements[0]
    assert "LIMIT :limit" in sql
    assert params is not None
    assert params["limit"] == 51, "limit+1 is how a next_cursor is detected"
    assert len(page) == 120, "the read layer pages in SQL; slicing to the page is the caller's job"


async def test_limit_is_capped_so_no_request_can_ask_for_the_world() -> None:
    """§110 "No unbounded queries"."""
    session = RecordingSession([])
    await InboxQuery.page(session, TENANT, limit=100_000)
    _, params = session.statements[0]
    assert params is not None
    assert params["limit"] <= InboxQuery.MAX_LIMIT + 1


# ------------------------------------- the read is not in the write service ---


def test_write_service_no_longer_performs_inbox_reads() -> None:
    """The register's complaint: "absent (joins in write service)".

    ``ConversationService`` owns facts (append_message, assign, close,
    mark_read). It must not also own the inbox projection: that is what makes
    a read cheap to fix and expensive to forget.
    """
    from app.modules.conversations.service import ConversationService

    assert not hasattr(ConversationService, "inbox_query"), (
        "the §137 inbox read still lives on the write service"
    )
    assert not hasattr(ConversationService, "list_inbox"), (
        "the §137 inbox read still lives on the write service"
    )
    service_src = (
        pathlib.Path(__file__).resolve().parents[1] / "app/modules/conversations/service.py"
    ).read_text(encoding="utf-8")
    assert "FROM conversations" not in service_src.lower(), (
        "the write service is still hand-writing inbox SQL"
    )
    assert "JOIN customers" not in service_src.lower(), (
        "the write service is still joining another module's table"
    )
    assert "get_name_phone_map" not in service_src, (
        "the write service is still reaching into customers for the list"
    )


def test_mark_read_fetches_nothing_it_throws_away() -> None:
    """A write path may not run a read whose result nobody looks at.

    ``mark_read`` used to ``session.execute(select(Message)...)`` and discard
    the cursor. It marked nothing: ``messages.status`` is the outbound delivery
    lifecycle (``models.py:172``, driven by provider receipts in
    ``gateway/ingest.py:302``), so there was no inbound read flag to set, and
    ``conversations.unread_count`` was already the only read marker the inbox
    has. The statement cost one round trip per call and hid the real question
    (does this system even track per-message reads?) inside a line that looked
    like an answer.
    """
    from app.modules.conversations.service import ConversationService

    body = inspect.getsource(ConversationService.mark_read)
    # Comments excluded on purpose: the function now DOCUMENTS the statement it
    # no longer runs, and a guard that reads prose as code fails for the reason
    # it exists to prevent.
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert "session.execute" not in code, (
        "mark_read is running a statement whose result it discards"
    )
    assert "select(Message)" not in code, (
        "mark_read is reading messages to mark something that has no read flag"
    )


def test_read_model_imports_no_other_module() -> None:
    """§137 reads via parameter-bound SQL, not another module's mapped classes.

    Same rule ``customers/timeline.py`` documents for the CUSTOMER 360
    projection, and the one the boundary ratchet in
    ``tests/test_module_boundaries.py`` exists to route around.
    """
    path = pathlib.Path(__file__).resolve().parents[1] / "app/modules/conversations/inbox.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.modules."):
            parts = node.module.split(".")
            if len(parts) > 2 and parts[2] != "conversations":
                offenders.append(node.module)
    assert offenders == [], f"the inbox read model reaches into other modules: {offenders}"


# ------------------------------------------------- the column guard -------

_ALIAS_RE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][\w]*)(?:\s+(?:AS\s+)?([a-z_]\w*))?", re.I)
_QUALIFIED_RE = re.compile(r"\b([a-z_]\w*)\.([a-z_]\w+)\b")
_FUNCTIONS = {"date_trunc", "coalesce", "left", "nullif", "count", "sum", "min", "max", "greatest"}


def _undefined_columns(sql: str) -> set[str]:
    """``alias.column`` tokens in *sql* that no such column exists for.

    A deliberately narrow checker: an alias it cannot resolve to a table is
    skipped rather than guessed at, so it can only report a column it has
    positively located in a real table and failed to find.
    """
    aliases: dict[str, str] = {}
    for table, alias in _ALIAS_RE.findall(sql):
        if table in Base.metadata.tables:
            aliases[alias or table] = table
        elif alias:
            aliases[alias] = None  # a subquery/CTE alias: nothing to check
    bad: set[str] = set()
    for alias, column in _QUALIFIED_RE.findall(sql):
        if column in _FUNCTIONS or alias not in aliases or aliases[alias] is None:
            continue
        table = Base.metadata.tables[aliases[alias]]
        if column not in table.c:
            bad.add(f"{aliases[alias]}.{column}")
    return bad


def test_column_guard_catches_an_invented_column() -> None:
    """The guard bites — it is what the shipped /inbox query needed.

    ``ConversationService.inbox_query`` selected three columns that no model
    and no migration ever defined, so ``GET /inbox`` raised
    ``ProgrammingError`` on every call, and no test noticed because no test
    called it. This is the smallest assertion that would have.
    """
    assert _undefined_columns(
        "SELECT c.id, c.last_message_preview FROM conversations c WHERE c.tenant_id = :t"
    ) == {"conversations.last_message_preview"}


def test_inbox_sql_references_only_real_columns() -> None:
    """Every qualified column the read model names exists in the schema.

    DB-free on purpose: the DB-backed tests skip without
    ``DATABASE_URL_APP_ADMIN``, so a locally-green suite must still be unable
    to ship a query against a column nobody created.
    """
    bad = _undefined_columns(_inbox_sql())
    assert bad == set(), f"the inbox read model selects columns that do not exist: {sorted(bad)}"


def _inbox_sql() -> str:
    """The SQL the read model issues, without running it."""
    import asyncio

    session = RecordingSession([])
    asyncio.run(InboxQuery.page(session, TENANT, status="open", limit=50))
    return session.statements[0][0]


# ------------------------------------------------------------------ PII ---


def test_phone_is_redacted_without_pii_read() -> None:
    """§146 on a read surface: the inbox page carries ``customer_phone``.

    Follows ``customers/router.py:_redact_issue_item`` — ``redact_fields`` with
    an EXPLICIT set, applied only when the caller lacks ``pii:read``. The key
    here is ``customer_phone``, which is not the bare ``phone`` in
    ``PII_FIELDS``, so the default set would silently ship it.
    """
    from app.modules.conversations.router import _redact_inbox_item

    item = {
        "id": str(CONVERSATION),
        "customer_name": "منى",
        "customer_phone": "+201000000000",
        "last_message_preview": "هل السعر نهائي؟",
    }
    out = _redact_inbox_item(item, permission_codes={"inbox:read"})
    assert out["customer_phone"] is None
    assert out["customer_name"] == "منى", "name is not PII in this repo's vocabulary"
    assert out["last_message_preview"] == "هل السعر نهائي؟"


def test_phone_survives_for_a_pii_reader() -> None:
    from app.modules.conversations.router import _redact_inbox_item

    item = {"id": "x", "customer_name": "منى", "customer_phone": "+201000000000"}
    assert _redact_inbox_item(item, permission_codes={"pii:read"})["customer_phone"]


# ---------------------------------------------------- CI-only real SQL ----
#
# These EXECUTE the statement, so they are the ones that prove the read model
# runs against the real schema. They skip locally without
# DATABASE_URL_APP_ADMIN and are CI's job.


def _counting_engine(bind):  # noqa: ANN001 - test helper
    """Attach a ``before_cursor_execute`` statement counter to whatever the test
    is bound to.

    `before_cursor_execute` is an event on BOTH an Engine and a Connection, and
    the db fixture's bind arrives as a plain Connection under CI (where RLS
    forces the session to share one real connection) and as an Engine elsewhere
    — `getattr(..., "sync_engine", bind)` covers the async forms too, since
    AsyncEngine and AsyncConnection both expose `sync_engine`.
    """
    from sqlalchemy import event

    counter = {"n": 0}

    @event.listens_for(getattr(bind, "sync_engine", bind), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        counter["n"] += 1

    return counter


@pytest.fixture
async def inbox_seed(db):
    """One customer, one conversation with 2 inbound + 1 outbound, one SLA.

    Two things have to be true before that seed can land, and CI is the only
    place that proves it (these tests skip without ``DATABASE_URL_APP_ADMIN``):

    * the tenant GUC is BOUND — CI executes as the ``sales_app`` role and the
      hardening sweep's ``tenant_isolation`` policy refuses every INSERT whose
      ``app.tenant_id`` is unset, even a correctly owned row (first seen as 5
      setup errors in run 36136180924);
    * the tenant EXISTS. Binding a synthetic UUID satisfies WITH CHECK and then
      dies one step later on ``fk_customers_tenant_id_tenants`` — 'DETAIL: Key
      is not present in table "tenants"' (run on c85e130). So this seeds a
      REAL ``Tenant`` row, the way ``tests/conftest.py``'s ``tenant_ctx`` does.
      Its id is pinned to this module's ``TENANT`` constant because the ~25
      DB-free tests above, and every ``InboxQuery.page(db, TENANT, …)`` below,
      name that uuid; ``default=uuid.uuid4`` on the column only fills in when
      the id is left unset.
    """
    from app.core.db import bind_tenant
    from app.modules.conversations.models import Conversation, Message
    from app.modules.customers.models import Customer
    from app.modules.identity.models import Tenant
    from app.modules.operations.models import SLAEvent

    db.add(
        Tenant(
            id=TENANT,
            slug=f"inbox-{uuid.uuid4().hex[:8]}",
            name="Inbox Read Model Tenant",
        )
    )
    await db.flush()

    await bind_tenant(db, TENANT)
    customer = Customer(tenant_id=TENANT, name="منى", phone="+201000000000")
    db.add(customer)
    await db.flush()
    conversation = Conversation(
        tenant_id=TENANT,
        customer_id=customer.id,
        channel="whatsapp",
        status="open",
        unread_count=2,
        last_message_at=NOW,
        assignee_user_id=None,
    )
    db.add(conversation)
    await db.flush()
    for i, direction in enumerate(("inbound", "inbound", "outbound")):
        db.add(
            Message(
                tenant_id=TENANT,
                conversation_id=conversation.id,
                direction=direction,
                sender_type="customer" if direction == "inbound" else "agent",
                body=f"رسالة {i}",
                created_at=NOW + timedelta(minutes=i),
                status="received" if direction == "inbound" else "sent",
            )
        )
    db.add(
        SLAEvent(
            tenant_id=TENANT,
            conversation_id=conversation.id,
            kind="first_response",
            status="running",
            deadline_at=NOW + timedelta(minutes=30),
        )
    )
    await db.flush()
    return SimpleNamespace(customer=customer, conversation=conversation)


async def test_page_reports_the_inbox_elements_from_live_rows(db, inbox_seed) -> None:
    page = await InboxQuery.page(db, TENANT, limit=50)
    assert len(page) == 1
    item = page[0]
    assert item["customer_name"] == "منى"
    assert item["unread_count"] == 2
    assert item["last_message_preview"] == "رسالة 2", "the newest message, not the oldest"
    assert item["last_message_direction"] == "outbound"
    assert item["sla_status"] == "running"


async def test_unread_cannot_drift_from_the_facts_it_projects(db, inbox_seed) -> None:
    """The read model has no copy of unread to go stale.

    A materialized projection would need §137's asynchronous updater and a
    reconciliation job; this reads ``conversations.unread_count``, which the
    write path moves inside the same transaction as the message insert
    (``add_message``), so the page and the counter are the same row. The
    assertion that keeps a future projection honest: after a write, the very
    next page already shows it — no lag window at all.
    """
    from app.modules.conversations.service import ConversationService

    before = await InboxQuery.page(db, TENANT, limit=50)
    assert before[0]["unread_count"] == 2

    await ConversationService.add_message(
        db,
        TENANT,
        conversation_id=inbox_seed.conversation.id,
        direction="inbound",
        sender_type="customer",
        body="أخرى",
    )
    await ConversationService.mark_read(db, TENANT, inbox_seed.conversation.id)

    page = await InboxQuery.page(db, TENANT, limit=50)
    assert page[0]["unread_count"] == 0, "read-after-write must not lag"
    # ... and the counter still cannot exceed what the messages support.
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from app.modules.conversations.models import Message

    inbound = (
        await db.execute(
            sa_select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == inbox_seed.conversation.id,
                Message.direction == "inbound",
            )
        )
    ).scalar_one()
    assert inbound == 3, "the messages table moved with the same write"


async def test_page_is_tenant_isolated(db, inbox_seed) -> None:
    """Raw SQL is not a tenancy hole: explicit predicate AND bound RLS.

    The stranger's row enters the table through the stranger's own hands —
    WITH CHECK refuses to let anyone mint a row owned by someone else — and
    then the page, bound and predicated to the seeded tenant, must not see it.

    The stranger is a SECOND REAL TENANT, not a bare UUID: its own customer
    row is FK-checked against ``tenants``, so a synthetic id would die on
    ``fk_customers_tenant_id_tenants`` before RLS ever got asked. Real and
    distinct is the point — nothing here is weakened by it, and the refusal at
    the bottom still has to come from row-level security rather than from an
    absent tenant.
    """
    from app.core.db import bind_tenant
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import Customer
    from app.modules.identity.models import Tenant

    db.add(
        Tenant(
            id=OTHER_TENANT,
            slug=f"inbox-x-{uuid.uuid4().hex[:8]}",
            name="Inbox Stranger Tenant",
        )
    )
    await db.flush()

    await bind_tenant(db, OTHER_TENANT)
    other = Customer(tenant_id=OTHER_TENANT, name="أخرى")
    db.add(other)
    await db.flush()
    foreign = Conversation(
        tenant_id=OTHER_TENANT, customer_id=other.id, channel="webchat", status="open"
    )
    db.add(foreign)
    await db.flush()

    await bind_tenant(db, TENANT)
    page = await InboxQuery.page(db, TENANT, limit=50)
    assert [i["id"] for i in page] == [str(inbox_seed.conversation.id)]

    db.add(
        Conversation(tenant_id=OTHER_TENANT, customer_id=other.id, channel="webchat", status="open")
    )
    with pytest.raises(Exception) as excinfo:  # RLS violation → ProgrammingError
        await db.flush()
    assert "row-level security" in str(excinfo.value).lower()
    await db.rollback()


async def test_one_page_costs_one_statement_on_a_real_database(db, inbox_seed) -> None:
    """The CI-only twin of the counting tests: real round trips, not calls."""
    engine = db.get_bind()
    counter = _counting_engine(engine)
    baseline = counter["n"]
    await InboxQuery.page(db, TENANT, status="open", limit=50)
    assert counter["n"] - baseline == 1, (
        f"a real inbox page cost {counter['n'] - baseline} statements, expected 1"
    )


async def test_preview_is_bounded_in_sql(db, inbox_seed) -> None:
    """§110 "No huge payloads": the preview is truncated WHERE it is read."""
    from app.modules.conversations.models import Message

    long_body = "ل" * (INBOX_PREVIEW_CHARS * 5)
    db.add(
        Message(
            tenant_id=TENANT,
            conversation_id=inbox_seed.conversation.id,
            direction="inbound",
            sender_type="customer",
            body=long_body,
            created_at=NOW + timedelta(hours=1),
            status="received",
        )
    )
    await db.flush()
    page = await InboxQuery.page(db, TENANT, limit=50)
    assert len(page[0]["last_message_preview"]) == INBOX_PREVIEW_CHARS
