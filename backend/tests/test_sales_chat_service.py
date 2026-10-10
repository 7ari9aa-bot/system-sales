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
