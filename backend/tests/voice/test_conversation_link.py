"""A spoken turn is a turn in the same conversation, and the schema has to prove it.

These tests are the ones that would fail if the voice layer drifted back into being a second
assistant: a session that cannot name its thread, a turn that cannot name its messages, a message
that cannot say it was spoken, or a speech provider that is allowed to carry more than it should.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.ai.models import AIChatMessage
from app.modules.voice.domain.models import VoiceSessionRow, VoiceTurnRow
from app.modules.voice.infrastructure.sql_store import _to_record
from app.modules.voice.security.data_egress import (
    PROVIDER_POLICIES,
    DataClass,
    EgressDecision,
    decide,
)

_MODEL = "openai/gpt-live-1.1"


def _row(**overrides: object) -> VoiceSessionRow:
    values = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "principal_type": "merchant_user",
        "persona": "merchant_assistant",
        "channel": "web_voice",
        "state": "ACTIVE",
        "authentication_level": 2,
        "scopes": ["analytics:read"],
        "policy_version": "v1",
        "trace_id": "trace-1",
    }
    values.update(overrides)
    return VoiceSessionRow(**values)


def test_the_session_remembers_which_conversation_it_is_talking_in() -> None:
    thread_id = uuid.uuid4()

    record = _to_record(_row(ai_chat_thread_id=thread_id))

    # The capability carries the thread, so a worker that restarts can resume the same
    # conversation instead of opening a new one and losing the context.
    assert record.capability.ai_chat_thread_id == thread_id


def test_a_session_without_a_thread_is_still_valid() -> None:
    # Every already-closed call predates the column; a NULL thread must read back as NULL, not
    # as an error that would make old rows unreadable.
    assert _to_record(_row(ai_chat_thread_id=None)).capability.ai_chat_thread_id is None


def test_a_turn_points_at_the_messages_it_became() -> None:
    user_message_id, assistant_message_id = uuid.uuid4(), uuid.uuid4()

    turn = VoiceTurnRow(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        sequence_number=1,
        speaker="user",
        state="ACTIVE",
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )

    assert turn.user_message_id == user_message_id
    assert turn.assistant_message_id == assistant_message_id


def test_a_message_says_how_it_arrived() -> None:
    message = AIChatMessage(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        sequence_no=1,
        role="user",
        input_modality="live_voice",
        output_modality="text",
        voice_session_id=uuid.uuid4(),
        transcript_status="final",
    )

    assert message.input_modality == "live_voice"
    assert message.voice_session_id is not None


def test_the_merchant_voice_may_carry_shop_metrics_but_no_customer_record() -> None:
    allowed = decide(provider="gpt_live", data_class=DataClass.INTERNAL, region="eu", model=_MODEL)
    assert allowed.decision is EgressDecision.ALLOW

    for denied_class in (DataClass.CONFIDENTIAL, DataClass.PII):
        verdict = decide(provider="gpt_live", data_class=denied_class, region="eu", model=_MODEL)
        assert verdict.decision is EgressDecision.DENY, denied_class


@pytest.mark.parametrize("region", ["eu", "us"])
def test_a_card_is_never_spoken_to_a_provider(region: str) -> None:
    verdict = decide(provider="gpt_live", data_class=DataClass.PAYMENT, region=region, model=_MODEL)
    assert verdict.decision is EgressDecision.DENY


def test_a_model_off_the_allowlist_is_refused() -> None:
    verdict = decide(
        provider="gpt_live", data_class=DataClass.INTERNAL, region="eu", model="other/model"
    )
    assert verdict.decision is EgressDecision.DENY


def test_an_unlisted_provider_is_refused() -> None:
    assert "gpt_live" in PROVIDER_POLICIES
    verdict = decide(
        provider="not-a-provider", data_class=DataClass.PUBLIC, region="eu", model=_MODEL
    )
    assert verdict.decision is EgressDecision.DENY


def test_the_policy_is_recorded_rather_than_assumed() -> None:
    policy = PROVIDER_POLICIES["gpt_live"]
    assert policy.allowed_classes == frozenset({DataClass.PUBLIC, DataClass.INTERNAL})
    assert DataClass.PII not in policy.allowed_classes
    assert policy.model_allowlist == frozenset({_MODEL})
    assert datetime.now(UTC)  # keeps the import honest if the module stops needing a clock
