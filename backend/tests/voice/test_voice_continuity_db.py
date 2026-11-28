"""A spoken turn lands in the conversation that was typed into.

Pressing the call button used to open a second conversation: the voice session always created its
own thread, so a merchant who typed a question and then talked got two separate conversations
with the same assistant. That is the opposite of "one assistant, two ways to talk to it".

Measured on the real database the CI shards provide: given the thread the client is already in,
the session continues it; without one it still opens its own; a thread from another shop is
refused with 404 semantics rather than adopted.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.core.errors import NotFoundError
from app.applications.apparel.modules.ai.chat import service as chat_service
from app.applications.apparel.modules.ai.models import Agent
from app.modules.voice.application.session_manager import VoiceSessionManager
from app.modules.voice.application.session_thread import ensure_session_thread
from app.modules.voice.domain.models import VoiceSessionRow
from app.modules.voice.domain.personas import PrincipalType
from app.modules.voice.infrastructure.sql_store import SqlSessionStore

SCOPES = frozenset({"assistant:use"})


async def _agent(db, tenant_id):
    agent = Agent(tenant_id=tenant_id, kind="sales_intelligence", name="مساعد المبيعات")
    db.add(agent)
    await db.flush()
    return agent


async def _session(db, tenant_ctx):
    manager = VoiceSessionManager(SqlSessionStore(db))
    return await manager.start(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=tenant_ctx.user.id,
        tenant_id=tenant_ctx.tenant_id,
        held_scopes=SCOPES,
        client_key=f"tab-{uuid.uuid4().hex[:8]}",
    )


async def _threads(db, tenant_id) -> int:
    return (
        await db.execute(
            sa.text("SELECT count(*) FROM ai_chat_threads WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
    ).scalar_one()


async def test_the_call_button_continues_the_typed_conversation(db, tenant_ctx) -> None:
    agent = await _agent(db, tenant_ctx.tenant_id)
    typed = await chat_service.create_thread(db, tenant_ctx, title="محادثة")
    record = await _session(db, tenant_ctx)

    thread_id = await ensure_session_thread(
        db, tenant_ctx, session_id=record.session_id, thread_id=typed.id
    )

    assert thread_id == typed.id
    row = (
        await db.execute(sa.select(VoiceSessionRow).where(VoiceSessionRow.id == record.session_id))
    ).scalar_one()
    assert row.ai_chat_thread_id == typed.id
    # one conversation, not two: the call did not open a thread of its own
    assert await _threads(db, tenant_ctx.tenant_id) == 1
    # and the same brain answers both ways — one agent row, the thread's agent
    stored = (
        await db.execute(
            sa.text("SELECT agent_id FROM ai_chat_threads WHERE id = :i"), {"i": str(typed.id)}
        )
    ).scalar_one()
    assert stored == agent.id


async def test_a_session_without_a_thread_still_opens_its_own(db, tenant_ctx) -> None:
    await _agent(db, tenant_ctx.tenant_id)
    record = await _session(db, tenant_ctx)

    thread_id = await ensure_session_thread(db, tenant_ctx, session_id=record.session_id)
    again = await ensure_session_thread(db, tenant_ctx, session_id=record.session_id)

    assert thread_id == again
    assert await _threads(db, tenant_ctx.tenant_id) == 1


async def test_another_shops_thread_is_never_adopted(db, tenant_ctx) -> None:
    from app.modules.identity.models import Tenant

    await _agent(db, tenant_ctx.tenant_id)
    mine = await chat_service.create_thread(db, tenant_ctx, title="محادثة")

    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    # Written AS the other shop: voice_sessions sits under RLS, so inserting its row while the
    # tenant GUC still names our shop is a privilege error, not a test of the adoption rule.
    their_ctx = SimpleNamespace(user=tenant_ctx.user, tenant_id=other.id)
    their_session = await _session(db, their_ctx)
    await bind_tenant(db, tenant_ctx.tenant_id)

    with pytest.raises(NotFoundError):
        await ensure_session_thread(
            db, tenant_ctx, session_id=their_session.session_id, thread_id=mine.id
        )
