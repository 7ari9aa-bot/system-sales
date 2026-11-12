"""A memory command through the REAL chat turn, with a real database and no mocks of memory.

The mocked chat tests prove the routing. This proves the part they cannot: that the note is really
in ``owner_memories`` afterwards, that the turn's own commit does not lose it, that the reply the
owner reads is the one stored, and that the model was never asked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import sqlalchemy as sa

from app.modules.ai.chat.turns import run_chat_turn
from app.modules.ai.models import Agent, AIChatMessage, AIChatThread, OwnerMemory


async def _thread_with_question(db, tenant_ctx, text: str):
    # one agent per kind per shop (uq_agents_tenant_kind): reuse it across questions
    agent = (
        await db.execute(
            sa.select(Agent).where(
                Agent.tenant_id == tenant_ctx.tenant_id, Agent.kind == "sales_intelligence"
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        agent = Agent(
            tenant_id=tenant_ctx.tenant_id,
            name="SI",
            model="fast",
            system_prompt="x",
            kind="sales_intelligence",
        )
        db.add(agent)
        await db.flush()
    thread = AIChatThread(
        tenant_id=tenant_ctx.tenant_id,
        agent_id=agent.id,
        created_by_user_id=tenant_ctx.user.id,
        title="",
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
            content=text,
        )
    )
    await db.flush()
    return thread


def _ctx(tenant_ctx):
    return SimpleNamespace(
        tenant_id=tenant_ctx.tenant_id,
        user=SimpleNamespace(id=tenant_ctx.user.id),
        role_code="owner",
        permission_codes={"analytics:read"},
    )


def _no_model(monkeypatch):
    called = []

    async def should_not_run(*a, **k):
        called.append(1)
        raise AssertionError("the model must not be called for a memory command")

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", should_not_run
    )
    return called


async def _rows(db, tenant_ctx):
    return (
        await db.execute(
            sa.select(OwnerMemory.content, OwnerMemory.source).where(
                OwnerMemory.tenant_id == tenant_ctx.tenant_id,
                OwnerMemory.user_id == tenant_ctx.user.id,
            )
        )
    ).all()


async def test_remember_through_the_real_turn_writes_the_note_and_stores_the_reply(
    db, tenant_ctx, monkeypatch
):
    called = _no_model(monkeypatch)
    thread = await _thread_with_question(db, tenant_ctx, "افتكر إن المورد الرئيسي اسمه حسين")
    answer = await run_chat_turn(db, _ctx(tenant_ctx), thread)

    assert called == []
    assert answer.status == "completed" and answer.role == "assistant"
    assert "المورد الرئيسي اسمه حسين" in answer.content
    assert [(r.content, r.source) for r in await _rows(db, tenant_ctx)] == [
        ("المورد الرئيسي اسمه حسين", "explicit")
    ]
    stored = (
        await db.execute(sa.select(AIChatMessage).where(AIChatMessage.id == answer.id))
    ).scalar_one()
    assert stored.content == answer.content


async def test_a_secret_through_the_real_turn_saves_nothing_and_is_not_copied_into_the_chat(
    db, tenant_ctx, monkeypatch
):
    _no_model(monkeypatch)
    secret = "الباسورد بتاعي Hunter22xyz"
    thread = await _thread_with_question(db, tenant_ctx, f"افتكر إن {secret}")
    answer = await run_chat_turn(db, _ctx(tenant_ctx), thread)

    assert await _rows(db, tenant_ctx) == []
    assert "ما حفظتش" in answer.content and "Hunter22xyz" not in answer.content
    every_message = (
        await db.execute(
            sa.select(AIChatMessage.content).where(AIChatMessage.thread_id == thread.id)
        )
    ).scalars()
    assert [c for c in every_message if "Hunter22xyz" in c] == [f"افتكر إن {secret}"], (
        "only the owner's own message holds it: nothing the system wrote repeats it"
    )


async def test_forget_all_through_the_real_turn_removes_the_words_from_the_table(
    db, tenant_ctx, monkeypatch
):
    _no_model(monkeypatch)
    for text in ("افتكر إن عندي فرعين", "افتكر إن بنقفل الجمعة"):
        t = await _thread_with_question(db, tenant_ctx, text)
        await run_chat_turn(db, _ctx(tenant_ctx), t)
    assert len(await _rows(db, tenant_ctx)) == 2

    t = await _thread_with_question(db, tenant_ctx, "انسى كل حاجة")
    answer = await run_chat_turn(db, _ctx(tenant_ctx), t)
    assert "2" in answer.content
    assert await _rows(db, tenant_ctx) == []
    raw = (
        await db.execute(
            sa.text("SELECT count(*) FROM owner_memories WHERE content LIKE '%فرعين%'")
        )
    ).scalar_one()
    assert raw == 0, "the words are gone from the table, not just hidden"


async def test_one_user_saving_never_shows_up_for_a_colleague_in_the_same_shop(
    db, tenant_ctx, monkeypatch
):
    from app.modules.identity.models import User

    _no_model(monkeypatch)
    t = await _thread_with_question(db, tenant_ctx, "افتكر إن سر نجاحي الصبر")
    await run_chat_turn(db, _ctx(tenant_ctx), t)

    colleague = User(email=f"c-{uuid.uuid4().hex[:8]}@t.local", password_hash="x", full_name="C")
    db.add(colleague)
    await db.flush()
    theirs = _ctx(tenant_ctx)
    theirs.user = SimpleNamespace(id=colleague.id)
    t2 = await _thread_with_question(db, tenant_ctx, "إيه اللي فاكره عني؟")
    answer = await run_chat_turn(db, theirs, t2)
    assert "سر نجاحي" not in answer.content and "مفيش" in answer.content


async def test_an_ordinary_question_through_the_real_turn_still_reaches_the_model(
    db, tenant_ctx, monkeypatch
):
    seen = []

    async def fake_analysis(session, tenant_id, **kw):
        seen.append(kw["question"])
        from tests.test_sales_chat_service import _analysis_result

        # run_id / analysis_id must exist in agent_runs (FK); this test is not about those rows
        return _analysis_result(saved_evidence_id=None, run_id=None, analysis_id=None)

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake_analysis
    )
    thread = await _thread_with_question(db, tenant_ctx, "تفتكر إيه اللي اتباع؟")
    await run_chat_turn(db, _ctx(tenant_ctx), thread)
    assert seen == ["تفتكر إيه اللي اتباع؟"]
    assert await _rows(db, tenant_ctx) == []
