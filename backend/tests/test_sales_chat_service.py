"""No-DB tests for the SI chat service — scripted session doubles.

DB truth (RLS as the app role, grants, FK enforcement) is CI's job —
tests/test_sales_chat_rls.py. Here we pin the SERVICE logic: idempotency
decisions, sequence arithmetic, visibility rules, status transitions, and
page caps.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.ai.chat import service as chat_service
from app.modules.ai.models import AIChatThread

TENANT = uuid.uuid4()
USER = uuid.uuid4()
OTHER_USER = uuid.uuid4()


class _FakeResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Pops one scripted result per execute(); records statements + adds."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.statements: list[object] = []
        self.added: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


class _Ctx:
    def __init__(self, *, tenant_id=TENANT, user_id=USER, role_code="member"):
        self.tenant_id = tenant_id
        self.user = SimpleNamespace(id=user_id)
        self.role_code = role_code


class _Thread:
    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.status = "active"
        self.title = ""
        self.last_message_at = None
        self.context = {}
        self.context_summary = None
        self.summary_through_seq = 0
        self.__dict__.update(kw)


def _fake_agent():
    return SimpleNamespace(id=uuid.uuid4())


# --- create_thread -------------------------------------------------------


async def test_create_thread_resolves_si_agent_server_side():
    session = _FakeSession([_FakeResult(_fake_agent())])
    ctx = _Ctx()
    await chat_service.create_thread(session, ctx, title="  تقرير  ")
    (added,) = session.added
    assert added.agent_id is not None
    assert added.tenant_id == TENANT
    assert added.created_by_user_id == USER
    assert added.title == "تقرير"  # stripped, never client-trusted agent_id


async def test_create_thread_rejects_oversized_title():
    session = _FakeSession([_FakeResult(_fake_agent())])
    with pytest.raises(ValidationError):
        await chat_service.create_thread(session, _Ctx(), title="x" * 201)


# --- get_thread visibility ----------------------------------------------


async def test_get_thread_hides_foreign_user_thread_from_member():
    foreign_thread = _Thread(created_by_user_id=OTHER_USER)
    session = _FakeSession([_FakeResult(foreign_thread)])
    with pytest.raises(NotFoundError):
        await chat_service.get_thread(session, _Ctx(), foreign_thread.id)


async def test_get_thread_shows_foreign_thread_to_tenant_owner():
    foreign_thread = _Thread(created_by_user_id=OTHER_USER)
    session = _FakeSession([_FakeResult(foreign_thread)])
    got = await chat_service.get_thread(session, _Ctx(role_code="owner"), foreign_thread.id)
    assert got is foreign_thread


async def test_get_thread_cross_tenant_is_404():
    session = _FakeSession([_FakeResult(None)])
    with pytest.raises(NotFoundError):
        await chat_service.get_thread(session, _Ctx(), uuid.uuid4())


# --- list_threads -------------------------------------------------------


async def test_list_threads_member_is_creator_scoped():
    session = _FakeSession([_FakeResult(rows=[])])
    await chat_service.list_threads(session, _Ctx(role_code="member"))
    (stmt,) = session.statements
    assert "created_by_user_id" in str(stmt.whereclause)


async def test_list_threads_owner_sees_whole_tenant():
    session = _FakeSession([_FakeResult(rows=[])])
    await chat_service.list_threads(session, _Ctx(role_code="owner"))
    (stmt,) = session.statements
    assert "created_by_user_id" not in str(stmt.whereclause)


async def test_list_threads_caps_limit_at_100():
    session = _FakeSession([_FakeResult(rows=[])])
    await chat_service.list_threads(session, _Ctx(), limit=500)
    (stmt,) = session.statements
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 100" in compiled


# --- update / delete ----------------------------------------------------


async def test_rename_rejects_empty_title():
    thread = _Thread(title="موجود")
    with pytest.raises(ValidationError):
        await chat_service.update_thread(_FakeSession(), _Ctx(), thread, title="   ")


async def test_archive_then_archive_conflicts():
    thread = _Thread(status="active")
    await chat_service.update_thread(_FakeSession(), _Ctx(), thread, status="archived")
    assert thread.status == "archived"
    with pytest.raises(ConflictError):
        await chat_service.update_thread(_FakeSession(), _Ctx(), thread, status="archived")


async def test_restore_after_archive_is_legal():
    thread = _Thread(status="archived")
    await chat_service.update_thread(_FakeSession(), _Ctx(), thread, status="active")
    assert thread.status == "active"


async def test_delete_thread_is_soft():
    thread = _Thread(status="active")
    await chat_service.delete_thread(_FakeSession(), _Ctx(), thread)
    assert thread.status == "deleted"


# --- append_user_message -------------------------------------------------


async def test_append_replays_idempotent_key_without_new_row():
    existing = SimpleNamespace(id=uuid.uuid4(), sequence_no=3)
    session = _FakeSession([_FakeResult(existing)])
    row, created = await chat_service.append_user_message(
        session, _Ctx(), _Thread(), content="سؤال", idempotency_key="key-1"
    )
    assert row is existing and created is False
    assert session.added == []


async def test_append_new_key_assigns_max_plus_one():
    session = _FakeSession([_FakeResult(None), _FakeResult(4)])
    thread = _Thread()
    row, created = await chat_service.append_user_message(
        session, _Ctx(), thread, content="سؤال جديد", idempotency_key="key-2"
    )
    (added,) = session.added
    assert created is True and added is row
    assert added.sequence_no == 5
    assert added.role == "user" and added.status == "completed"
    assert thread.last_message_at is not None


async def test_append_rejects_blank_and_oversized_content():
    with pytest.raises(ValidationError):
        await chat_service.append_user_message(
            _FakeSession(), _Ctx(), _Thread(), content="   ", idempotency_key=None
        )
    with pytest.raises(ValidationError):
        await chat_service.append_user_message(
            _FakeSession(), _Ctx(), _Thread(), content="x" * 4001, idempotency_key=None
        )


async def test_append_rejects_oversized_idempotency_key():
    with pytest.raises(ValidationError):
        await chat_service.append_user_message(
            _FakeSession(), _Ctx(), _Thread(), content="سؤال", idempotency_key="k" * 65
        )


# --- list_messages -------------------------------------------------------


async def test_list_messages_caps_limit_and_applies_before_seq():
    session = _FakeSession([_FakeResult(rows=[])])
    await chat_service.list_messages(session, _Ctx(), _Thread(), limit=500, before_seq=10)
    (stmt,) = session.statements
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 100" in compiled
    assert "sequence_no" in str(stmt.whereclause)


# --- the model the service builds (sanity for the migration diff) --------


def test_thread_model_table_name_is_stable():
    assert AIChatThread.__tablename__ == "ai_chat_threads"


# --- turn executor (Task 3) ----------------------------------------------

from datetime import UTC, datetime  # noqa: E402 — turn tests live below the fold

from app.modules.ai.agents.sales_intelligence.agent import AnalysisResult  # noqa: E402
from app.modules.ai.chat.schemas import MessageOut  # noqa: E402
from app.modules.ai.chat.turns import (  # noqa: E402
    HISTORY_MESSAGE_LIMIT,
    _bounded_history,
    _maybe_compact,
    run_chat_turn,
)
from app.modules.analytics.contracts import (  # noqa: E402
    DataQuality,
    DataQualityStatus,
    Finding,
    Outcome,
    Relationship,
)


class _CommittingSession(_FakeSession):
    def __init__(self, results=None):
        super().__init__(results)
        self.commits = 0

    async def commit(self):
        # a flush would assign the Python-side PK defaults; mirror that so
        # ORM rows added in the test have the ids the wire contract needs
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
        self.commits += 1
        return None


def _analysis_result(**overrides):
    base = dict(
        outcome=Outcome.ANSWERED,
        answer="المبيعات ارتفعت 12 بالمئة مقارنة بالشهر الماضي.",
        findings=[
            Finding(
                statement="الإيراد ارتفع",
                type="FACT",
                relationship=Relationship.OBSERVED,
                evidence_refs=["F1"],
                confidence="HIGH",
            )
        ],
        facts=[
            {"metric": "revenue", "value": "12500.00", "unit": "EGP", "window": "30d"}
        ],
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        guardrail_reason=None,
        saved_evidence_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
    )
    base.update(overrides)
    return AnalysisResult(**base)


async def test_run_chat_turn_persists_answer_and_blocks(monkeypatch):
    user_row = SimpleNamespace(sequence_no=1, content="قارن مبيعات الشهر ده باللي فات.")
    history_rows = [
        SimpleNamespace(role="user", content=user_row.content),
    ]
    session = _CommittingSession(
        [
            _FakeResult(rows=[user_row]),   # last user message
            _FakeResult(None),               # no assistant row at slot 2
            _FakeResult(rows=history_rows),  # bounded history
        ]
    )
    thread = _Thread(agent_id=uuid.uuid4())
    recorded = {}

    async def fake_analysis(session, tenant_id, *, agent_id, question, runner=None, history=None):
        recorded["question"] = question
        recorded["agent_id"] = agent_id
        recorded["history"] = history
        return _analysis_result()

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake_analysis
    )

    assistant = await run_chat_turn(session, _Ctx(), thread)

    assert recorded["question"] == user_row.content
    assert recorded["agent_id"] == thread.agent_id
    assert recorded["history"] == [{"role": "user", "content": user_row.content}]
    (added,) = session.added
    assert added is assistant
    assert assistant.status == "completed"
    assert assistant.sequence_no == 2
    assert assistant.run_id is not None and assistant.analysis_id is not None
    assert thread.title == user_row.content[:60]
    # durable before the model call, terminal after
    assert session.commits >= 2
    # the stored blocks validate against the wire contract
    MessageOut(
        id=assistant.id,
        thread_id=assistant.thread_id,
        sequence_no=assistant.sequence_no,
        role=assistant.role,
        status=assistant.status,
        content=assistant.content,
        structured_content=assistant.structured_content,
        run_id=assistant.run_id,
        analysis_id=assistant.analysis_id,
        error_code=None,
        created_at=datetime.now(UTC),
    )


async def test_run_chat_turn_failure_lands_failed_row(monkeypatch):
    user_row = SimpleNamespace(sequence_no=1, content="سؤال")
    session = _CommittingSession(
        [
            _FakeResult(rows=[user_row]),
            _FakeResult(None),
            _FakeResult(rows=[]),
        ]
    )

    async def boom(session, tenant_id, *, agent_id, question, runner=None, history=None):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", boom
    )
    with pytest.raises(ConflictError):
        await run_chat_turn(session, _Ctx(), _Thread(agent_id=uuid.uuid4()))
    (assistant,) = session.added
    assert assistant.status == "failed"
    assert assistant.error_code == "run_failed"


async def test_run_chat_turn_retry_overwrites_failed_row(monkeypatch):
    user_row = SimpleNamespace(sequence_no=1, content="سؤال")
    failed = SimpleNamespace(
        sequence_no=2,
        role="assistant",
        status="failed",
        content="",
        structured_content=None,
        error_code="run_failed",
        run_id=None,
        analysis_id=None,
    )
    session = _CommittingSession(
        [
            _FakeResult(rows=[user_row]),
            _FakeResult(failed),             # retry slot holds a failed row
            _FakeResult(rows=[]),
        ]
    )
    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis",
        lambda *a, **k: _async_result(_analysis_result()),
    )
    assistant = await run_chat_turn(session, _Ctx(), _Thread(agent_id=uuid.uuid4()))
    assert assistant is failed  # the SAME row is reused — no sequence burn
    assert assistant.status == "completed"
    assert session.added == []


class _Async:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        if False:
            yield
        return self._value


def _async_result(value):
    return _Async(value)


async def test_run_chat_turn_conflicts_when_answer_already_exists():
    user_row = SimpleNamespace(sequence_no=1, content="سؤال")
    answered = SimpleNamespace(sequence_no=2, role="assistant", status="completed")
    session = _CommittingSession([_FakeResult(rows=[user_row]), _FakeResult(answered)])
    with pytest.raises(ConflictError):
        await run_chat_turn(session, _Ctx(), _Thread(agent_id=uuid.uuid4()))
    assert session.commits == 0  # refused before any state moved


async def test_bounded_history_summary_marker_replaces_old_turns():
    rows = [
        SimpleNamespace(role="user", content="سؤال قديم"),
        SimpleNamespace(role="assistant", content="جواب قديم"),
    ]
    session = _FakeSession([_FakeResult(rows=rows)])
    thread = _Thread(summary_through_seq=2, context_summary="ملخص محسوب")
    history = await _bounded_history(session, _Ctx(), thread, through_seq=4)
    assert history[0]["content"].startswith("[Prior conversation summary]")
    assert history[1:] == [
        {"role": "user", "content": "سؤال قديم"},
        {"role": "assistant", "content": "جواب قديم"},
    ]


async def test_bounded_history_caps_at_limit_without_summary():
    # the fake cannot enforce SQL LIMIT; the cap is asserted on the compiled
    # statement, and the ordering transformation on what a capped page returns
    rows = [
        SimpleNamespace(role="user" if i % 2 == 0 else "assistant", content=f"t{i}")
        for i in range(HISTORY_MESSAGE_LIMIT)
    ]
    session = _FakeSession([_FakeResult(rows=rows)])
    history = await _bounded_history(session, _Ctx(), _Thread(), through_seq=20)
    (stmt,) = session.statements
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert f"LIMIT {HISTORY_MESSAGE_LIMIT}" in compiled
    assert history == [{"role": m.role, "content": m.content} for m in reversed(rows)]


async def test_maybe_compact_rebuilds_summary_deterministically():
    assistant_rows = [
        SimpleNamespace(
            sequence_no=2,
            status="completed",
            structured_content=[
                {"type": "kpi", "metric": "revenue", "value": "1", "unit": "EGP", "window": "30d"}
            ],
        ),
        SimpleNamespace(sequence_no=4, status="failed", structured_content=None),
    ]
    session = _FakeSession([_FakeResult(rows=assistant_rows)])
    thread = _Thread(summary_through_seq=0)
    await _maybe_compact(session, _Ctx(), thread, through_seq=14)
    assert thread.summary_through_seq == 14
    assert "turn 1: completed — revenue" in thread.context_summary
    assert "turn 3: failed" in thread.context_summary


async def test_maybe_compact_skips_small_threads():
    session = _FakeSession()
    thread = _Thread(summary_through_seq=0)
    await _maybe_compact(session, _Ctx(), thread, through_seq=HISTORY_MESSAGE_LIMIT)
    assert thread.context_summary is None
    assert session.statements == []
