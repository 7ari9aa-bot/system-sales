"""A real chat turn writes its steps while it runs, and the answer is the same with or without them.

The wiring is the risky part: a tool is called deep inside the shared runner, on the turn's own
session, and the step has to appear on the answer's row for a page that is polling from another
connection. So this runs the real ``run_chat_turn`` with a model that really calls a tool, and
looks at the row from INSIDE the tool call (while the answer is still `generating`), not after.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as si_tools
from app.applications.apparel.modules.ai.chat import progress as progress_module
from app.applications.apparel.modules.ai.chat import turns
from app.applications.apparel.modules.ai.chat.progress import STEP_TEXT
from app.applications.apparel.modules.ai.gateway import AIGateway
from app.applications.apparel.modules.ai.models import AIChatMessage, AIChatThread
from app.applications.apparel.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from tests.test_si_agent import _seed

QUESTION = "كام مبيعات الشهر ده؟"
ANSWER = "المبيعات في الفترة دي صفر، ومفيش أوردرات مسجلة."


def _script(monkeypatch, *calls):
    """The model asks for each tool in turn, then answers. Returns how many times it ran."""
    results = [
        ChatCompletionResult(
            content=None,
            tool_calls=[ToolCallRequest(id=f"c{i}", name=name, arguments=args)],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )
        for i, (name, args) in enumerate(calls)
    ] + [
        ChatCompletionResult(
            content=ANSWER, tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        )
    ]
    seen = {"n": 0}

    async def fake(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen["n"] += 1
        return results[min(seen["n"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake)
    return seen


@pytest.fixture
def writer_on_the_test_session(db, monkeypatch):
    """The writer opens its own session in production; here it is the test's, so rows are shared."""

    class _Shared:
        """The test's session, except that a commit only flushes: committing it would close the
        turn's own transaction, which in production the writer's SEPARATE session never touches
        (test_chat_progress_steps proves the writer does commit on its own session)."""

        async def execute(self, *a, **k):
            return await db.execute(*a, **k)

        async def commit(self):
            await db.flush()

    class _Ctx:
        async def __aenter__(self):
            return _Shared()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(progress_module.core_db, "get_sessionmaker", lambda: lambda: _Ctx())

    async def _bind(*a, **k):
        return None

    monkeypatch.setattr(progress_module, "bind_tenant", _bind)
    return db


async def _thread_with_question(db, tenant_ctx):
    agent = await _seed(db, tenant_ctx.tenant_id)
    # Tests enable the analytics agent explicitly rather than relying on the default,
    # so a change to analytics_agent.enabled's default never silently flips these tests.
    from app.modules.settings.service import SettingsService

    await SettingsService(db, tenant_ctx.tenant_id).set(
        "analytics_agent.enabled", True, bypass_approval=True
    )
    thread = AIChatThread(
        tenant_id=tenant_ctx.tenant_id,
        agent_id=agent.id,
        title="",
        created_by_user_id=tenant_ctx.user.id,
    )
    db.add(thread)
    await db.flush()
    db.add(
        AIChatMessage(
            tenant_id=tenant_ctx.tenant_id,
            thread_id=thread.id,
            sequence_no=1,
            role="user",
            status="completed",
            content=QUESTION,
        )
    )
    await db.flush()
    return thread


def _ctx(tenant_ctx):
    class _C:
        tenant_id = tenant_ctx.tenant_id
        user = tenant_ctx.user
        permission_codes = {"analytics:read", "finance:read", "inventory:read", "orders:read"}

    return _C()


async def _the_answer_row(db, thread):
    from sqlalchemy import select

    return (
        await db.execute(
            select(AIChatMessage).where(
                AIChatMessage.thread_id == thread.id, AIChatMessage.role == "assistant"
            )
        )
    ).scalar_one()


async def test_the_step_is_on_the_row_while_the_tool_runs_and_the_answer_is_unchanged(
    db, tenant_ctx, monkeypatch, writer_on_the_test_session
):
    thread = await _thread_with_question(db, tenant_ctx)
    _script(
        monkeypatch,
        ("si_metric", {"mode": "value", "metric_name": "orders_placed", "days": 30}),
    )
    seen_inside: dict = {}
    real = si_tools._si_metric

    async def spy(*args, **kwargs):
        row = await _the_answer_row(db, thread)
        seen_inside["status"] = row.status
        seen_inside["progress"] = list(row.progress or [])
        return await real(*args, **kwargs)

    monkeypatch.setattr(si_tools, "_si_metric", spy)
    from app.applications.apparel.modules.ai.tools import TOOLS

    TOOLS.pop("si_metric", None)
    si_tools.register_si_tools()

    answer = await turns.run_chat_turn(db, _ctx(tenant_ctx), thread)

    # the page would have seen this DURING the run: generating, with the step already written
    assert seen_inside["status"] == "generating"
    assert seen_inside["progress"] == [STEP_TEXT["sales"]]
    assert answer.status == "completed"
    assert ANSWER in answer.content


async def test_two_tools_show_two_steps_in_the_order_they_started(
    db, tenant_ctx, monkeypatch, writer_on_the_test_session
):
    thread = await _thread_with_question(db, tenant_ctx)
    _script(
        monkeypatch,
        ("si_metric", {"mode": "value", "metric_name": "orders_placed", "days": 30}),
        ("si_shop", {"view": "stock"}),
    )
    from app.applications.apparel.modules.ai.tools import TOOLS

    for name in ("si_metric", "si_shop"):
        TOOLS.pop(name, None)
    si_tools.register_si_tools()

    answer = await turns.run_chat_turn(db, _ctx(tenant_ctx), thread)
    row = await _the_answer_row(db, thread)
    assert answer.status == "completed"
    # the finished answer keeps the steps it went through, in order
    assert row.progress == [STEP_TEXT["sales"], STEP_TEXT["stock"]]


async def test_a_writer_that_cannot_write_never_changes_the_answer(
    db, tenant_ctx, monkeypatch, writer_on_the_test_session
):
    thread = await _thread_with_question(db, tenant_ctx)
    _script(
        monkeypatch,
        ("si_metric", {"mode": "value", "metric_name": "orders_placed", "days": 30}),
    )

    def broken():
        raise RuntimeError("database refused the step")

    monkeypatch.setattr(progress_module.core_db, "get_sessionmaker", broken)
    from app.applications.apparel.modules.ai.tools import TOOLS

    TOOLS.pop("si_metric", None)
    si_tools.register_si_tools()

    answer = await turns.run_chat_turn(db, _ctx(tenant_ctx), thread)
    assert answer.status == "completed"
    assert ANSWER in answer.content
    assert (await _the_answer_row(db, thread)).progress is None


async def test_a_question_with_no_tool_has_no_steps(
    db, tenant_ctx, monkeypatch, writer_on_the_test_session
):
    thread = await _thread_with_question(db, tenant_ctx)
    _script(monkeypatch)  # the model answers straight away
    answer = await turns.run_chat_turn(db, _ctx(tenant_ctx), thread)
    assert answer.status == "completed"
    assert (await _the_answer_row(db, thread)).progress is None
