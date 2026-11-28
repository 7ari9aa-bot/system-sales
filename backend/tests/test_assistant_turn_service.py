"""One brain, two carriers: a spoken turn is a turn, not a second conversation.

The service is the only door a turn walks through, so these tests pin the two
things that make voice safe to add: the conversation (thread + agent) comes from
the thread and never from the caller, and the modality changes nothing about who
thinks. The runtime itself is stubbed here on purpose — ``run_chat_turn`` is
covered by its own tests, and what is under test is that BOTH modalities reach
it through the same door, on the same thread.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.ai.assistant.contracts import LIVE_VOICE, TEXT, AssistantTurnInput
from app.applications.apparel.modules.ai.assistant.service import AssistantTurnService

TENANT = uuid.uuid4()
AGENT = uuid.uuid4()
THREAD = uuid.uuid4()


def _thread(**over):
    base = dict(id=THREAD, tenant_id=TENANT, agent_id=AGENT)
    base.update(over)
    return SimpleNamespace(**base)


def _ctx():
    return SimpleNamespace(tenant_id=TENANT)


@pytest.fixture
def runtime(monkeypatch):
    """The real execution, stubbed: records every call, answers on its thread."""
    calls: list[uuid.UUID] = []

    async def fake_run_chat_turn(session, ctx, thread):
        calls.append(thread.id)
        return SimpleNamespace(
            id=uuid.uuid4(),
            thread_id=thread.id,
            content="المبيعات زادت 12%",
            status="completed",
        )

    monkeypatch.setattr("app.applications.apparel.modules.ai.chat.turns.run_chat_turn", fake_run_chat_turn)
    return calls


async def test_a_text_turn_answers_with_the_conversation_it_belongs_to(runtime):
    turn = AssistantTurnInput(tenant_id=TENANT, thread_id=THREAD, modality=TEXT)

    result = await AssistantTurnService().run(None, _ctx(), _thread(), turn)

    assert result.thread_id == THREAD
    assert result.agent_id == AGENT
    assert result.modality == TEXT
    assert result.content == "المبيعات زادت 12%"
    assert result.message.id == result.assistant_message_id
    assert runtime == [THREAD]


async def test_a_voice_turn_lands_on_the_same_thread_and_agent_as_a_text_turn(runtime):
    service = AssistantTurnService()
    voice_session = uuid.uuid4()

    text = await service.run(
        None,
        _ctx(),
        _thread(),
        AssistantTurnInput(tenant_id=TENANT, thread_id=THREAD, modality=TEXT),
    )
    voice = await service.run(
        None,
        _ctx(),
        _thread(),
        AssistantTurnInput(
            tenant_id=TENANT,
            thread_id=THREAD,
            modality=LIVE_VOICE,
            voice_session_id=voice_session,
        ),
    )

    # Same conversation, same brain, one runtime call per turn — and the voice
    # session is a reference on the turn, never a second thread.
    assert voice.thread_id == text.thread_id == THREAD
    assert voice.agent_id == text.agent_id == AGENT
    assert voice.modality == LIVE_VOICE
    assert voice.assistant_message_id != text.assistant_message_id
    assert runtime == [THREAD, THREAD]


async def test_an_unknown_modality_is_refused_before_the_runtime_runs(runtime):
    turn = AssistantTurnInput(tenant_id=TENANT, thread_id=THREAD, modality="telepathy")

    with pytest.raises(ValidationError) as caught:
        await AssistantTurnService().run(None, _ctx(), _thread(), turn)

    assert caught.value.code == "unsupported_modality"
    assert runtime == []


async def test_a_turn_for_another_thread_is_refused(runtime):
    turn = AssistantTurnInput(tenant_id=TENANT, thread_id=uuid.uuid4(), modality=LIVE_VOICE)

    with pytest.raises(ValidationError) as caught:
        await AssistantTurnService().run(None, _ctx(), _thread(), turn)

    assert caught.value.code == "thread_mismatch"
    assert runtime == []
