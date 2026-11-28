"""Phase 5: a voice note on any channel, one transcript, and no identity invented from a handle."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.errors import ValidationError
from app.platform.voice.application.omnichannel import (
    AsyncVoicePipeline,
    InboundVoiceNote,
)
from app.platform.voice.application.session_manager import (
    InMemorySessionStore,
    VoiceSessionManager,
)
from app.platform.voice.domain.channels import MediaMode, contract_for
from app.platform.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
)
from app.platform.voice.security.channel_identity import (
    ChannelHandle,
    ChannelIdentityResolver,
    HandleLink,
    InMemoryLinkStore,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER = uuid.UUID("22222222-2222-2222-2222-222222222222")
NOW = dt.datetime(2026, 11, 27, 10, 0, tzinfo=dt.UTC)


class FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    async def transcribe(self, media_ref: str, *, language: str) -> str:
        self.calls.append(media_ref)
        return self.text


async def _answer(text: str, session) -> str:
    return f"heard: {text}"


def _pipeline(*, linked: bool = False, text: str = "فيه مقاس XL؟") -> AsyncVoicePipeline:
    links = InMemoryLinkStore()
    if linked:
        links._rows[  # noqa: SLF001 - the store is the test's own double
            (ChannelType.WHATSAPP_VOICE, "201000000000", TENANT)
        ] = HandleLink(
            handle=ChannelHandle(
                channel=ChannelType.WHATSAPP_VOICE,
                external_id="201000000000",
                tenant_id=TENANT,
            ),
            customer_id=CUSTOMER,
            level=AuthenticationLevel.VERIFIED,
            proved_at=NOW,
            method="otp",
        )
    resolver = ChannelIdentityResolver(links, clock=lambda: NOW)
    return AsyncVoicePipeline(
        resolver=resolver,
        sessions=VoiceSessionManager(InMemorySessionStore(), clock=lambda: NOW),
        transcriber=FakeTranscriber(text),
        responder=_answer,
        clock=lambda: NOW,
    )


def _note(**over: object) -> InboundVoiceNote:
    base = {
        "tenant_id": TENANT,
        "channel": ChannelType.WHATSAPP_VOICE,
        "external_id": "201000000000",
        "media_ref": "att_1",
        "seconds": 12,
        "conversation_id": uuid.uuid4(),
    }
    base.update(over)
    return InboundVoiceNote(**base)  # type: ignore[arg-type]


class TestChannelContracts:
    def test_every_declared_channel_can_carry_audio_in_some_mode(self) -> None:
        for channel in ChannelType:
            contract = contract_for(channel)
            assert contract.modes, channel

    def test_a_note_longer_than_the_channel_allows_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            contract_for(ChannelType.WHATSAPP_VOICE).check_note(121)

    def test_a_realtime_only_channel_refuses_a_note(self) -> None:
        with pytest.raises(ValidationError):
            contract_for(ChannelType.PSTN).check_note(5)

    def test_pstn_is_not_treated_as_a_voice_note_channel(self) -> None:
        assert not contract_for(ChannelType.PSTN).accepts(MediaMode.VOICE_NOTE)
        assert contract_for(ChannelType.WHATSAPP_VOICE).accepts(MediaMode.VOICE_NOTE)


class TestVoiceNote:
    async def test_an_unlinked_handle_gets_an_anonymous_session_not_a_customer(self) -> None:
        result = await _pipeline(linked=False).handle(_note())
        assert result.customer_id is None
        assert result.level is AuthenticationLevel.ANONYMOUS
        assert "no proved link" in result.identity_reason
        assert result.session.capability.principal_id is None

    async def test_a_proved_link_carries_the_customer_into_the_session(self) -> None:
        result = await _pipeline(linked=True).handle(_note())
        assert result.customer_id == CUSTOMER
        assert result.session.capability.principal_id == CUSTOMER
        assert "customer.own_orders:read" in result.session.capability.scopes

    async def test_the_note_is_transcribed_and_answered_on_the_same_conversation(self) -> None:
        conversation = uuid.uuid4()
        pipeline = _pipeline(text="عايز أعرف سعر المنتج")
        result = await pipeline.handle(_note(conversation_id=conversation))
        assert result.transcript == "عايز أعرف سعر المنتج"
        assert result.reply == "heard: عايز أعرف سعر المنتج"
        assert result.conversation_id == conversation
        assert result.channel is ChannelType.WHATSAPP_VOICE
        assert pipeline._transcriber.calls == ["att_1"]  # noqa: SLF001

    async def test_an_empty_transcript_is_not_answered(self) -> None:
        result = await _pipeline(text="   ").handle(_note())
        assert result.transcript == ""
        assert result.reply is None

    async def test_two_channels_share_one_conversation(self) -> None:
        conversation = uuid.uuid4()
        pipeline = _pipeline()
        first = await pipeline.handle(_note(conversation_id=conversation))
        second = await pipeline.handle(
            _note(conversation_id=conversation, channel=ChannelType.CHAT_VOICE, media_ref="att_2")
        )
        assert first.conversation_id == second.conversation_id == conversation
        assert first.channel is not second.channel
        assert first.session.session_id != second.session.session_id
