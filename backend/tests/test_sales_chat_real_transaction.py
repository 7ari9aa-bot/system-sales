"""The SI chat send route on a REAL request transaction (production shape).

Why this file exists: ``test_sales_chat_api.py`` drives the route with a scripted session
double, and every DB-backed test runs inside one outer transaction with
``join_transaction_mode="create_savepoint"``. In both, ``commit()`` is harmless. In production
``get_db`` opens ``async with session.begin()`` around the request, so a ``commit()`` inside
the route ENDS that transaction, and the next statement on the same session raises
``InvalidRequestError: Can't operate on closed transaction inside context manager``.

``send_sales_chat_message`` did exactly that (commit, then ``bind_tenant``). Every send returned
500 in production, the user's message was saved and no answer ever was: 11 questions, 0 replies.
3805 tests passed throughout.

Here the real ``get_db`` and ``get_tenant_ctx`` run over a real committed tenant, on real
connections. Only the login check and the model call are replaced.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.main import create_app
from app.modules.ai.agents.sales_intelligence.agent import AnalysisResult
from app.modules.analytics.contracts import DataQuality, DataQualityStatus, Outcome
from app.modules.identity.deps import AuthedUser, get_current_user
from tests._pos_helpers import make_tenant, purge_test_tenant

ANSWER = "الإيراد ارتفع 12 بالمئة."


def _result() -> AnalysisResult:
    return AnalysisResult(
        outcome=Outcome.ANSWERED,
        answer=ANSWER,
        facts=[{"metric": "revenue", "value": "12500.00", "unit": "EGP", "window": "30d"}],
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        saved_evidence_id=None,
        run_id=None,
        analysis_id=None,
    )


@pytest.fixture
async def shop(db_url, admin_url, monkeypatch):
    """A committed tenant with an owner, the SI agent and a thread, on real connections."""
    # The route's own session factory must point at the real database, not at a test savepoint.
    engine, factory, tenant_id, user_id = await make_tenant(db_url, "sichat")
    app_engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: app_factory)
    try:
        async with factory() as s:
            await bind_tenant(s, tenant_id)
            agent_id = (
                await s.execute(
                    sa.text(
                        "INSERT INTO agents (id, tenant_id, name, kind, is_active) "
                        "VALUES (gen_random_uuid(), :t, 'Sales Intelligence', "
                        "'sales_intelligence', true) RETURNING id"
                    ),
                    {"t": tenant_id},
                )
            ).scalar_one()
            thread_id = (
                await s.execute(
                    sa.text(
                        "INSERT INTO ai_chat_threads (id, tenant_id, agent_id, "
                        "created_by_user_id, title) VALUES (gen_random_uuid(), :t, :a, :u, "
                        "'t') RETURNING id"
                    ),
                    {"t": tenant_id, "a": agent_id, "u": user_id},
                )
            ).scalar_one()
            await s.commit()
        yield {
            "factory": factory,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "thread_id": thread_id,
        }
    finally:
        # The chat tables are cleared with the OWNER connection: the app role may not relax
        # triggers, and a leftover tenant would pollute every later run.
        owner = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
        try:
            async with owner.begin() as conn:
                await conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
                for table in ("ai_chat_messages", "ai_chat_threads", "agents"):
                    await conn.execute(
                        sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                        {"t": tenant_id},
                    )
        finally:
            await owner.dispose()
        await purge_test_tenant(admin_url, tenant_id, user_id)
        await engine.dispose()
        await app_engine.dispose()


def _client(shop) -> AsyncClient:
    app = create_app()

    async def _user():
        return AuthedUser(
            id=shop["user_id"],
            tenant_id=shop["tenant_id"],
            role_code="owner",
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _rows(shop):
    async with shop["factory"]() as s:
        await bind_tenant(s, shop["tenant_id"])
        return (
            await s.execute(
                sa.text(
                    "SELECT role, status, content FROM ai_chat_messages "
                    "WHERE thread_id = :t ORDER BY sequence_no"
                ),
                {"t": shop["thread_id"]},
            )
        ).all()


async def test_send_message_answers_on_a_real_request_transaction(shop, monkeypatch):
    async def fake(session, tenant_id, *, agent_id, question, runner=None, history=None, **_):
        return _result()

    monkeypatch.setattr("app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake)

    async with _client(shop) as client:
        res = await client.post(
            f"/api/v1/ai/sales-chat/threads/{shop['thread_id']}/messages",
            json={"content": "قارن مبيعات الشهر ده باللي فات.", "idempotency_key": "real-1"},
        )

    assert res.status_code == 201, res.text
    assert res.json()["content"] == ANSWER
    rows = await _rows(shop)
    assert [(r.role, r.status) for r in rows] == [("user", "completed"), ("assistant", "completed")]
    assert rows[1].content == ANSWER


async def test_replaying_the_same_key_returns_the_saved_answer_without_a_second_run(
    shop, monkeypatch
):
    runs = {"n": 0}

    async def fake(session, tenant_id, *, agent_id, question, runner=None, history=None, **_):
        runs["n"] += 1
        return _result()

    monkeypatch.setattr("app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake)
    url = f"/api/v1/ai/sales-chat/threads/{shop['thread_id']}/messages"
    body = {"content": "أحسن المنتجات؟", "idempotency_key": "real-2"}

    async with _client(shop) as client:
        first = await client.post(url, json=body)
        second = await client.post(url, json=body)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["content"] == ANSWER
    assert runs["n"] == 1, "the replay must not run (and bill) the analysis again"
    assert len(await _rows(shop)) == 2


async def test_a_failed_analysis_leaves_a_failed_row_that_can_be_retried(shop, monkeypatch):
    state = {"boom": True}

    async def fake(session, tenant_id, *, agent_id, question, runner=None, history=None, **_):
        if state["boom"]:
            raise RuntimeError("model unreachable")
        return _result()

    monkeypatch.setattr("app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake)
    url = f"/api/v1/ai/sales-chat/threads/{shop['thread_id']}/messages"

    async with _client(shop) as client:
        failed = await client.post(url, json={"content": "سؤال", "idempotency_key": "real-3"})
        assert failed.status_code == 409, failed.text
        rows = await _rows(shop)
        assert [(r.role, r.status) for r in rows] == [
            ("user", "completed"),
            ("assistant", "failed"),
        ]

        state["boom"] = False
        listing = (
            await client.get(f"/api/v1/ai/sales-chat/threads/{shop['thread_id']}/messages")
        ).json()
        # The listing is newest-first, so pick the failed assistant row by what it IS.
        failed_id = next(m["id"] for m in listing if m["role"] == "assistant")
        retried = await client.post(
            f"/api/v1/ai/sales-chat/threads/{shop['thread_id']}/messages/{failed_id}/retry"
        )

    assert retried.status_code == 200, retried.text
    assert retried.json()["content"] == ANSWER
    assert [(r.role, r.status) for r in await _rows(shop)] == [
        ("user", "completed"),
        ("assistant", "completed"),
    ]
