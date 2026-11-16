"""The steps shown while the assistant works are real, ordered, plain Arabic, and cost no answer.

Before this the owner saw three bouncing dots for about fifteen seconds. Each step is now written
when that thing really starts. Two rules matter more than the wording: a step is written on its own
short session (committing on the turn's session closed its transaction once and made every send
return 500), and writing a step can never raise, so a database that refuses it costs a step and
never the answer.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.modules.ai.chat import progress as progress_module
from app.modules.ai.chat.progress import STEP_TEXT, TOOL_STEP, note_step, step_for_tool
from app.modules.ai.models import AIChatMessage, AIChatThread
from tests.test_si_agent import _seed

LATIN = re.compile(r"[A-Za-z_]{2,}")


def test_every_owner_tool_has_a_step_and_no_step_names_a_tool_that_does_not_exist():
    assert set(TOOL_STEP) == set(SI_TOOLS)
    assert set(TOOL_STEP.values()) == set(STEP_TEXT)


def test_there_is_no_writing_step_because_nothing_marks_the_last_model_call():
    # a "writing the reply" line would also fire while the model is only choosing a tool
    assert "writing" not in STEP_TEXT
    assert not any("الرد" in text for text in STEP_TEXT.values())


def test_the_wording_is_plain_arabic_with_no_internal_word():
    for key, text in STEP_TEXT.items():
        assert text.strip() and not LATIN.search(text), (key, text)
        assert "si_" not in text


def test_a_tool_with_no_wording_shows_no_step_rather_than_a_wrong_one():
    assert step_for_tool("not_a_tool") is None
    assert step_for_tool(None) is None
    assert step_for_tool("si_metric") == "sales"


async def _generating_row(db, tenant_ctx, status="generating") -> AIChatMessage:
    agent = await _seed(db, tenant_ctx.tenant_id)
    thread = AIChatThread(
        tenant_id=tenant_ctx.tenant_id,
        agent_id=agent.id,
        title="t",
        created_by_user_id=tenant_ctx.user.id,
    )
    db.add(thread)
    await db.flush()
    row = AIChatMessage(
        tenant_id=tenant_ctx.tenant_id,
        thread_id=thread.id,
        sequence_no=2,
        role="assistant",
        status=status,
        content="",
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
def own_session(db, monkeypatch):
    """Route the writer's own session to the test's, which sees the same uncommitted rows."""

    class _Factory:
        def __call__(self):
            return _Ctx()

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(progress_module.core_db, "get_sessionmaker", lambda: _Factory())
    return db


async def test_a_step_is_recorded_on_the_generating_answer(db, tenant_ctx, own_session):
    row = await _generating_row(db, tenant_ctx)
    await note_step(tenant_ctx.tenant_id, row.id, "sales")
    await db.refresh(row)
    assert row.progress == [STEP_TEXT["sales"]]


async def test_steps_keep_their_order_and_never_repeat(db, tenant_ctx, own_session):
    row = await _generating_row(db, tenant_ctx)
    for step in ("sales", "stock", "sales", "finance", "stock"):
        await note_step(tenant_ctx.tenant_id, row.id, step)
    await db.refresh(row)
    assert row.progress == [STEP_TEXT["sales"], STEP_TEXT["stock"], STEP_TEXT["finance"]]


async def test_an_unknown_step_writes_nothing(db, tenant_ctx, own_session):
    row = await _generating_row(db, tenant_ctx)
    await note_step(tenant_ctx.tenant_id, row.id, "made_up")
    await db.refresh(row)
    assert row.progress is None


@pytest.mark.parametrize("status", ["completed", "failed", "pending", "cancelled"])
async def test_a_late_step_never_lands_on_an_answer_that_is_not_generating(
    db, tenant_ctx, own_session, status
):
    # the answer is already in: a step arriving now would only make the finished reply flicker
    row = await _generating_row(db, tenant_ctx, status=status)
    await note_step(tenant_ctx.tenant_id, row.id, "sales")
    await db.refresh(row)
    assert row.progress is None


async def test_a_message_that_does_not_exist_is_ignored(db, tenant_ctx, own_session):
    await note_step(tenant_ctx.tenant_id, uuid.uuid4(), "sales")  # must not raise


async def test_a_database_that_refuses_the_write_costs_the_step_never_the_answer(
    tenant_ctx, monkeypatch
):
    def broken():
        raise RuntimeError("database is down")

    monkeypatch.setattr(progress_module.core_db, "get_sessionmaker", broken)
    # if this raised, the question being answered would fail because of a courtesy line
    await note_step(tenant_ctx.tenant_id, uuid.uuid4(), "sales")


async def test_a_failure_while_writing_is_swallowed_too(db, tenant_ctx, own_session, monkeypatch):
    row = await _generating_row(db, tenant_ctx)

    async def explode(*a, **k):
        raise RuntimeError("write refused")

    monkeypatch.setattr(db, "execute", explode)
    await note_step(tenant_ctx.tenant_id, row.id, "sales")  # must not raise


async def test_two_steps_written_at_once_both_survive(db, tenant_ctx, own_session):
    # the first version read the list into Python and wrote it back, so a second step that read
    # the same stale copy erased the first. The write is now one statement.
    import asyncio

    row = await _generating_row(db, tenant_ctx)
    await asyncio.gather(
        note_step(tenant_ctx.tenant_id, row.id, "sales"),
        note_step(tenant_ctx.tenant_id, row.id, "stock"),
        note_step(tenant_ctx.tenant_id, row.id, "finance"),
    )
    await db.refresh(row)
    assert sorted(row.progress) == sorted(
        [STEP_TEXT["sales"], STEP_TEXT["stock"], STEP_TEXT["finance"]]
    )


async def test_the_step_text_is_stored_as_a_plain_string_not_quoted_json(
    db, tenant_ctx, own_session
):
    row = await _generating_row(db, tenant_ctx)
    await note_step(tenant_ctx.tenant_id, row.id, "stock")
    await db.refresh(row)
    assert row.progress[0] == "بشوف المخزون"  # not '"بشوف المخزون"'


async def test_the_step_is_committed_so_a_second_connection_can_see_it(db, tenant_ctx, monkeypatch):
    # the page that polls reads from ITS OWN connection: a step left uncommitted is invisible to
    # it, and the whole feature would show nothing while every test on one connection passed
    row = await _generating_row(db, tenant_ctx)
    committed = {"n": 0}

    class _Spy:
        def __init__(self, inner):
            self._inner = inner

        async def execute(self, *a, **k):
            return await self._inner.execute(*a, **k)

        async def commit(self):
            committed["n"] += 1
            await self._inner.flush()

    class _Ctx:
        async def __aenter__(self):
            return _Spy(db)

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(progress_module.core_db, "get_sessionmaker", lambda: lambda: _Ctx())
    monkeypatch.setattr(progress_module, "bind_tenant", lambda *a, **k: _noop())
    await note_step(tenant_ctx.tenant_id, row.id, "sales")
    assert committed["n"] == 1


async def _noop():
    return None


async def test_after_a_turn_ends_a_tool_announces_nothing(db, tenant_ctx, own_session):
    # the answer's id lives in a context variable. If it outlived the turn, a tool called later
    # (a scheduled job, the older /ai/sales route) would write steps onto a finished answer
    from app.modules.ai.chat.progress import announce, announcing_to

    row = await _generating_row(db, tenant_ctx)
    with announcing_to(tenant_ctx.tenant_id, row.id):
        await announce("sales")
    await announce("stock")  # outside the block: nobody is waiting for this
    await db.refresh(row)
    assert row.progress == [STEP_TEXT["sales"]]


async def test_the_context_is_restored_even_when_the_turn_raises(db, tenant_ctx, own_session):
    from app.modules.ai.chat.progress import _CURRENT_ANSWER, announcing_to

    with pytest.raises(RuntimeError), announcing_to(tenant_ctx.tenant_id, uuid.uuid4()):
        raise RuntimeError("the turn failed")
    assert _CURRENT_ANSWER.get() is None


def test_a_wrapped_tool_keeps_the_signature_the_runner_reads():
    # the runner passes `context` only to a handler that declares it; a wrapper that hid the
    # parameter would silently stop every tool that needs it
    import inspect

    from app.modules.ai.chat.progress import with_progress

    async def handler(session, tenant_id, *, days: int = 30, context=None):
        return days

    wrapped = with_progress("si_metric", handler)
    assert list(inspect.signature(wrapped).parameters) == list(
        inspect.signature(handler).parameters
    )
    assert "context" in inspect.signature(wrapped).parameters
    assert wrapped.__name__ == handler.__name__


async def test_a_wrapped_tool_still_returns_what_the_handler_returns():
    from app.modules.ai.chat.progress import with_progress

    async def handler(session, tenant_id, *, days: int = 30):
        return {"days": days}

    assert await with_progress("si_metric", handler)(None, None, days=7) == {"days": 7}
    # a tool the page has no wording for runs silently rather than announcing a wrong line
    assert await with_progress("not_a_tool", handler)(None, None, days=3) == {"days": 3}
