"""A finished spoken turn leaves ONE turn row, linked to both of its messages.

The gap this pins was invisible to unit tests: the live path wrote the question through
``chat.service.append_user_message`` and the answer through the shared runtime, while
``transcript_sync`` — the module that knows the contract — was never called. The result was a
conversation with no ``voice_session_id`` on any row and a ``voice_turns`` table with no rows at
all, so a call could not be traced back to what was said, and "resume from turn N" had nothing to
resume from.

Measured on the real database the CI shards provide (``db``/``tenant_ctx`` fixtures, transactional
rollback) and skipped cleanly when no database URL is configured. The model itself is stubbed: the
answer row is written the way the runtime writes it — plain, with no voice fields — because the
point of the test is that the LIVE PATH adds them.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.core.db import bind_tenant
from app.modules.ai.assistant.contracts import AssistantTurnResult
from app.modules.ai.assistant.service import AssistantTurnService
from app.modules.ai.models import Agent, AIChatMessage
from app.modules.voice.application import assistant_turn
from app.modules.voice.application.session_manager import VoiceSessionManager
from app.modules.voice.domain.models import VoiceSessionRow, VoiceTurnRow
from app.modules.voice.domain.personas import PrincipalType
from app.modules.voice.infrastructure.sql_store import SqlSessionStore

SCOPES = frozenset({"assistant:use"})
ANSWER = "الأوردر اتشحن امبارح الساعة ستة"


async def _agent(db, tenant_id: uuid.UUID) -> Agent:
    agent = Agent(tenant_id=tenant_id, kind="sales_intelligence", name="مساعد المبيعات")
    db.add(agent)
    await db.flush()
    return agent


async def _live_session(db, tenant_ctx):
    """A session in the state a browser call reaches: provider named, then ACTIVE."""
    manager = VoiceSessionManager(SqlSessionStore(db))
    record = await manager.start(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=tenant_ctx.user.id,
        tenant_id=tenant_ctx.tenant_id,
        held_scopes=SCOPES,
        client_key=f"tab-{uuid.uuid4().hex[:8]}",
    )
    await manager.attach_provider(record.session_id, f"prov-{uuid.uuid4().hex[:8]}")
    return await manager.activate(record.session_id)


def _stub_brain(calls: list):
    """Write the answer exactly like ``run_chat_turn`` does: no voice fields at all."""

    async def run(self, session, ctx, thread, turn):
        calls.append(turn)
        next_seq = (
            await session.execute(
                sa.select(sa.func.coalesce(sa.func.max(AIChatMessage.sequence_no), 0)).where(
                    AIChatMessage.thread_id == thread.id
                )
            )
        ).scalar_one() + 1
        row = AIChatMessage(
            tenant_id=ctx.tenant_id,
            thread_id=thread.id,
            sequence_no=next_seq,
            role="assistant",
            status="completed",
            content=ANSWER,
        )
        session.add(row)
        await session.flush()
        return AssistantTurnResult(
            thread_id=thread.id,
            agent_id=thread.agent_id,
            assistant_message_id=row.id,
            content=ANSWER,
            status="completed",
            modality=turn.modality,
            message=row,
        )

    return run


async def _turns(db, session_id: uuid.UUID) -> list[VoiceTurnRow]:
    return list(
        (
            await db.execute(
                sa.select(VoiceTurnRow)
                .where(VoiceTurnRow.session_id == session_id)
                .order_by(VoiceTurnRow.sequence_number)
            )
        )
        .scalars()
        .all()
    )


async def _messages(db, thread_id: uuid.UUID) -> list[AIChatMessage]:
    return list(
        (
            await db.execute(
                sa.select(AIChatMessage)
                .where(AIChatMessage.thread_id == thread_id)
                .order_by(AIChatMessage.sequence_no)
            )
        )
        .scalars()
        .all()
    )


async def _session_row(db, session_id: uuid.UUID) -> VoiceSessionRow:
    return (
        await db.execute(sa.select(VoiceSessionRow).where(VoiceSessionRow.id == session_id))
    ).scalar_one()


async def test_one_completed_turn_is_one_turn_row_linked_to_both_messages(
    db, tenant_ctx, monkeypatch
) -> None:
    await _agent(db, tenant_ctx.tenant_id)
    record = await _live_session(db, tenant_ctx)
    calls: list = []
    monkeypatch.setattr(AssistantTurnService, "run", _stub_brain(calls))

    result = await assistant_turn.run_voice_turn(
        db,
        tenant_ctx,
        session_id=record.session_id,
        text="الأوردر وصل؟",
        idempotency_key="delegation:d-1",
    )
    # The turn commits, which ends the transaction-local RLS binding.
    await bind_tenant(db, tenant_ctx.tenant_id)

    assert calls and calls[0].voice_session_id == record.session_id

    turns = await _turns(db, record.session_id)
    assert len(turns) == 1, "one spoken turn is one voice_turns row"
    turn = turns[0]
    assert turn.sequence_number == 1
    assert turn.state == "COMPLETED"
    assert turn.completed_at is not None
    assert turn.user_message_id is not None
    assert turn.assistant_message_id is not None
    assert turn.user_message_id != turn.assistant_message_id

    messages = await _messages(db, result.thread_id)
    assert [m.id for m in messages] == [turn.user_message_id, turn.assistant_message_id]
    question, answer = messages
    assert question.role == "user" and answer.role == "assistant"
    # The whole point: BOTH rows say which call they belong to, so a transcript can be
    # reconstructed from the conversation and a call can be found from its words.
    assert question.voice_session_id == record.session_id
    assert answer.voice_session_id == record.session_id
    assert question.input_modality == "live_voice"
    assert answer.output_modality == "live_voice"
    assert question.idempotency_key == "delegation:d-1"

    session_row = await _session_row(db, record.session_id)
    assert session_row.last_completed_turn == 1
    # Recording a turn is not a lifecycle move: the call is still live.
    assert session_row.state == "ACTIVE"


async def test_a_replayed_key_adds_no_second_message_and_no_second_turn(
    db, tenant_ctx, monkeypatch
) -> None:
    await _agent(db, tenant_ctx.tenant_id)
    record = await _live_session(db, tenant_ctx)
    calls: list = []
    monkeypatch.setattr(AssistantTurnService, "run", _stub_brain(calls))

    first = await assistant_turn.run_voice_turn(
        db,
        tenant_ctx,
        session_id=record.session_id,
        text="الأوردر وصل؟",
        idempotency_key="delegation:d-2",
    )
    await bind_tenant(db, tenant_ctx.tenant_id)
    replayed = await assistant_turn.run_voice_turn(
        db,
        tenant_ctx,
        session_id=record.session_id,
        text="الأوردر وصل؟",
        idempotency_key="delegation:d-2",
    )
    await bind_tenant(db, tenant_ctx.tenant_id)

    # The same answer, without a second model call and without a second row.
    assert replayed.content == first.content
    assert len(calls) == 1
    assert len(await _messages(db, first.thread_id)) == 2
    assert len(await _turns(db, record.session_id)) == 1
    assert (await _session_row(db, record.session_id)).last_completed_turn == 1


async def test_a_second_question_is_the_second_turn(db, tenant_ctx, monkeypatch) -> None:
    await _agent(db, tenant_ctx.tenant_id)
    record = await _live_session(db, tenant_ctx)
    monkeypatch.setattr(AssistantTurnService, "run", _stub_brain([]))

    for key, text in (("delegation:d-3", "الأوردر وصل؟"), ("delegation:d-4", "ومبيعات النهاردة؟")):
        await assistant_turn.run_voice_turn(
            db, tenant_ctx, session_id=record.session_id, text=text, idempotency_key=key
        )
        await bind_tenant(db, tenant_ctx.tenant_id)

    turns = await _turns(db, record.session_id)
    assert [t.sequence_number for t in turns] == [1, 2]
    assert all(t.user_message_id and t.assistant_message_id for t in turns)
    assert len({t.user_message_id for t in turns}) == 2
    assert (await _session_row(db, record.session_id)).last_completed_turn == 2
