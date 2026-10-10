"""Route-contract tests for /ai/sales-chat/* — real ASGI stack, overridden deps.

The _IncludedRouter lesson: walking app.routes finds nothing, so every claim
goes through an httpx client. The tenant context is overridden with a
scripted session double; the DB-backed guarantees live in
tests/test_sales_chat_rls.py (CI).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.ai.agents.sales_intelligence.agent import AnalysisResult
from app.modules.ai.models import AIChatThread
from app.modules.analytics.contracts import DataQuality, DataQualityStatus, Outcome
from app.modules.identity.deps import AuthedUser, get_tenant_ctx

TENANT = uuid.uuid4()
USER = uuid.uuid4()


class _FakeResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def first(self):
        return self._rows[0] if self._rows else self._value

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.statements: list[object] = []
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self._assign_ids()

    async def commit(self):
        self._assign_ids()
        self.commits += 1

    def _assign_ids(self):
        # a flush would fire the server defaults too — mirror the ones the
        # response contracts read so the ORM rows serialize like real rows
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "status", None) is None:
                obj.status = "active"
            if getattr(obj, "created_at", None) is None:
                now = datetime.now(UTC)
                obj.created_at = now
                if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
                    obj.updated_at = now


def _thread(**kw) -> AIChatThread:
    return AIChatThread(
        id=kw.get("id", uuid.uuid4()),
        tenant_id=TENANT,
        agent_id=kw.get("agent_id", uuid.uuid4()),
        created_by_user_id=kw.get("created_by_user_id", USER),
        title=kw.get("title", "تقرير الشهر"),
        status=kw.get("status", "active"),
        context={},
        context_summary=None,
        summary_through_seq=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_message_at=None,
    )


def _app(session: _FakeSession, *, role_code: str = "member") -> FastAPI:
    app = create_app()

    async def _ctx():
        return TenantContextLike(session, role_code)

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def TenantContextLike(session, role_code):  # noqa: N802 — mirrors the analytics test's shape
    from app.modules.identity.deps import TenantContext

    return TenantContext(
        session=session,
        user=AuthedUser(id=USER, tenant_id=TENANT, role_code=role_code),
        tenant_id=TENANT,
        role_code=role_code,
        permission_codes={"analytics:read"},
    )


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _analysis_result():
    return AnalysisResult(
        outcome=Outcome.ANSWERED,
        answer="الإيراد ارتفع 12 بالمئة.",
        facts=[{"metric": "revenue", "value": "12500.00", "unit": "EGP", "window": "30d"}],
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        saved_evidence_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
    )


def _patch_analysis(monkeypatch, *, explode=False, result=None):
    calls = {"count": 0}

    async def fake(session, tenant_id, *, agent_id, question, runner=None, history=None):
        if explode:
            raise AssertionError("the analysis must not run again for a replayed key")
        calls["count"] += 1
        return result or _analysis_result()

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake
    )
    return calls


async def test_create_thread_returns_201_and_resolves_agent_server_side():
    session = _FakeSession([_FakeResult(SimpleNamespace(id=uuid.uuid4()))])
    async with _client(_app(session)) as client:
        res = await client.post(
            "/api/v1/ai/sales-chat/threads",
            json={"title": "تقرير", "context": {"period": "30d"}},
        )
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "تقرير"
    assert body["status"] == "active"
    assert "agent_id" not in body  # the wire never takes a client agent id


async def test_send_message_happy_path_returns_assistant_turn(monkeypatch):
    thread = _thread()
    user_row = SimpleNamespace(sequence_no=1, content="قارن مبيعات الشهر ده باللي فات.")
    session = _FakeSession(
        [
            _FakeResult(thread),               # get_thread
            _FakeResult(None),                 # idempotency lookup
            _FakeResult(0),                    # max sequence_no
            _FakeResult(rows=[user_row]),      # run_chat_turn: last user message
            _FakeResult(None),                 # run_chat_turn: assistant slot free
            _FakeResult(rows=[]),              # bounded history
        ]
    )
    calls = _patch_analysis(monkeypatch)

    async with _client(_app(session)) as client:
        res = await client.post(
            f"/api/v1/ai/sales-chat/threads/{thread.id}/messages",
            json={"content": "قارن مبيعات الشهر ده باللي فات.", "idempotency_key": "k-1"},
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["role"] == "assistant"
    assert body["status"] == "completed"
    assert body["content"] == "الإيراد ارتفع 12 بالمئة."
    kinds = [b["type"] for b in body["structured_content"]]
    assert "text" in kinds and "kpi" in kinds and "refs" in kinds
    assert calls["count"] == 1


async def test_duplicate_idempotency_key_returns_same_reply_without_rerun(monkeypatch):
    thread = _thread()
    user_row = SimpleNamespace(id=uuid.uuid4(), sequence_no=1, content="سؤال")
    reply = SimpleNamespace(
        id=uuid.uuid4(),
        thread_id=thread.id,
        sequence_no=2,
        role="assistant",
        status="completed",
        content="الإيراد ارتفع 12 بالمئة.",
        structured_content=[{"type": "text", "body": "الإيراد ارتفع 12 بالمئة."}],
        run_id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        error_code=None,
        created_at=datetime.now(UTC),
    )
    session = _FakeSession(
        [
            _FakeResult(thread),      # get_thread
            _FakeResult(user_row),    # idempotency lookup -> existing user turn
            _FakeResult(reply),       # assistant reply for seq 2
        ]
    )
    _patch_analysis(monkeypatch, explode=True)

    async with _client(_app(session)) as client:
        res = await client.post(
            f"/api/v1/ai/sales-chat/threads/{thread.id}/messages",
            json={"content": "سؤال", "idempotency_key": "k-1"},
        )
    assert res.status_code == 201
    assert res.json()["id"] == str(reply.id)


async def test_send_rejects_oversized_content_with_422():
    session = _FakeSession()
    async with _client(_app(session)) as client:
        res = await client.post(
            f"/api/v1/ai/sales-chat/threads/{uuid.uuid4()}/messages",
            json={"content": "x" * 4001},
        )
    assert res.status_code == 422


async def test_foreign_thread_is_404_for_member():
    foreign = _thread(created_by_user_id=uuid.uuid4())
    session = _FakeSession([_FakeResult(foreign)])
    async with _client(_app(session)) as client:
        res = await client.get(f"/api/v1/ai/sales-chat/threads/{foreign.id}")
    assert res.status_code == 404


async def test_cross_tenant_thread_is_404():
    session = _FakeSession([_FakeResult(None)])
    async with _client(_app(session)) as client:
        res = await client.get(f"/api/v1/ai/sales-chat/threads/{uuid.uuid4()}")
    assert res.status_code == 404


async def test_patch_archive_then_restore():
    thread = _thread()
    session = _FakeSession([_FakeResult(thread), _FakeResult(thread)])
    async with _client(_app(session)) as client:
        archived = await client.patch(
            f"/api/v1/ai/sales-chat/threads/{thread.id}", json={"status": "archived"}
        )
        restored = await client.patch(
            f"/api/v1/ai/sales-chat/threads/{thread.id}", json={"status": "active"}
        )
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert restored.status_code == 200 and restored.json()["status"] == "active"


async def test_patch_archive_twice_conflicts():
    thread = _thread(status="archived")
    session = _FakeSession([_FakeResult(thread)])
    async with _client(_app(session)) as client:
        res = await client.patch(
            f"/api/v1/ai/sales-chat/threads/{thread.id}", json={"status": "archived"}
        )
    assert res.status_code == 409


async def test_delete_then_get_is_404():
    thread = _thread()
    session = _FakeSession([_FakeResult(thread), _FakeResult(None)])
    async with _client(_app(session)) as client:
        deleted = await client.delete(f"/api/v1/ai/sales-chat/threads/{thread.id}")
        fetched = await client.get(f"/api/v1/ai/sales-chat/threads/{thread.id}")
    assert deleted.status_code == 204
    assert fetched.status_code == 404


async def test_retry_conflicts_on_completed_turn():
    thread = _thread()
    answered = SimpleNamespace(sequence_no=2, role="assistant", status="completed")
    session = _FakeSession([_FakeResult(thread), _FakeResult(answered)])
    _patch_analysis(pytest.MonkeyPatch(), explode=True)
    async with _client(_app(session)) as client:
        res = await client.post(
            f"/api/v1/ai/sales-chat/threads/{thread.id}/messages/{uuid.uuid4()}/retry"
        )
    assert res.status_code == 409


async def test_retry_reruns_a_failed_turn(monkeypatch):
    thread = _thread()
    user_row = SimpleNamespace(sequence_no=1, content="سؤال")
    failed = SimpleNamespace(
        id=uuid.uuid4(),
        thread_id=thread.id,
        created_at=datetime.now(UTC),
        sequence_no=2, role="assistant", status="failed", content="", structured_content=None,
        error_code="run_failed", run_id=None, analysis_id=None,
    )
    session = _FakeSession(
        [
            _FakeResult(thread),               # get_thread
            _FakeResult(failed),               # retry: the stale row is failed
            _FakeResult(rows=[user_row]),      # retry: latest user turn matches the slot
            _FakeResult(rows=[user_row]),      # run_chat_turn: last user message
            _FakeResult(failed),               # run_chat_turn: failed slot reused
            _FakeResult(rows=[]),              # bounded history
        ]
    )
    calls = _patch_analysis(monkeypatch)
    async with _client(_app(session)) as client:
        res = await client.post(
            f"/api/v1/ai/sales-chat/threads/{thread.id}/messages/{uuid.uuid4()}/retry"
        )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "completed"
    assert calls["count"] == 1
