"""A bare greeting on a REAL request transaction: answered at once, with no analysis, no model call,
and a normal saved row. A real question in the same thread still runs the analysis."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.modules.ai.gateway import AIGateway
from tests import test_sales_chat_real_transaction as _real

ANSWER, _client, _result = _real.ANSWER, _real._client, _real._result
shop = _real.shop


@pytest.fixture
def calls(monkeypatch):
    seen = {"analysis": 0, "model": 0}

    async def analysis(session, tenant_id, *, agent_id, question, runner=None, history=None, **_):
        seen["analysis"] += 1
        return _result()

    async def chat(self, session, tenant_id, **kw):
        seen["model"] += 1
        raise AssertionError("a greeting must not reach the model")

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", analysis
    )
    monkeypatch.setattr(AIGateway, "chat", chat)
    return seen


async def _send(shop, content, key):
    async with _client(shop) as client:
        return await client.post(
            f"/api/v1/ai/sales-chat/threads/{shop['thread_id']}/messages",
            json={"content": content, "idempotency_key": key},
        )


async def _rows(shop):
    async with shop["factory"]() as s:
        await bind_tenant(s, shop["tenant_id"])
        return (
            await s.execute(
                sa.text(
                    "SELECT sequence_no, role, status, content, run_id, structured_content "
                    "FROM ai_chat_messages WHERE thread_id = :t ORDER BY sequence_no"
                ),
                {"t": shop["thread_id"]},
            )
        ).all()


async def test_a_greeting_is_answered_without_analysis_or_model(shop, calls):
    resp = await _send(shop, "هلا", "k-hi")
    assert resp.status_code in (200, 201, 202), resp.text
    rows = await _rows(shop)
    assert [r.role for r in rows] == ["user", "assistant"]
    reply = rows[1]
    assert reply.status == "completed"
    assert reply.content and len(reply.content) <= 80 and "\n" not in reply.content
    assert reply.run_id is None  # nothing ran, so there is no run to cite
    assert reply.structured_content == [{"type": "text", "body": reply.content}]
    assert calls == {"analysis": 0, "model": 0}


async def test_a_real_question_still_runs_the_analysis(shop, calls):
    await _send(shop, "هلا كام مبيعات النهاردة", "k-q")
    assert calls["analysis"] == 1
    rows = await _rows(shop)
    assert rows[1].status == "completed" and rows[1].content == ANSWER


async def test_thanks_after_an_answer_is_a_short_welcome_and_adds_one_turn(shop, calls):
    await _send(shop, "كام مبيعات النهاردة", "k-1")
    await _send(shop, "شكرا", "k-2")
    rows = await _rows(shop)
    assert [r.sequence_no for r in rows] == [1, 2, 3, 4]
    assert rows[3].content == "العفو، أي وقت."
    assert calls["analysis"] == 1


async def test_the_greeting_is_idempotent(shop, calls):
    a = await _send(shop, "هلا", "k-same")
    b = await _send(shop, "هلا", "k-same")
    assert a.status_code == b.status_code
    assert len(await _rows(shop)) == 2


async def test_a_greeting_names_the_thread_so_the_list_is_not_untitled(shop, calls):
    async with shop["factory"]() as s:
        await bind_tenant(s, shop["tenant_id"])
        await s.execute(
            sa.text("UPDATE ai_chat_threads SET title = '' WHERE id = :t"), {"t": shop["thread_id"]}
        )
        await s.commit()
    await _send(shop, "هلا", "k-title")
    async with shop["factory"]() as s:
        await bind_tenant(s, shop["tenant_id"])
        title = (
            await s.execute(
                sa.text("SELECT title FROM ai_chat_threads WHERE id = :t"), {"t": shop["thread_id"]}
            )
        ).scalar_one()
    assert title and title.strip()
