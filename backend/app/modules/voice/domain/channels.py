"""What each channel can actually do, declared once so nothing is assumed at runtime.

A WhatsApp voice note is not a phone call: it arrives whole, it has no barge-in, and it may be two
minutes long. Webchat voice is realtime but the caller can also type. The pipeline asks this
registry before it promises a capability, so an unsupported request is a refusal instead of a
silent downgrade the customer never hears about.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core.errors import ValidationError
from app.modules.voice.security.capabilities import ChannelType


class MediaMode(enum.StrEnum):
    REALTIME = "realtime"
    VOICE_NOTE = "voice_note"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ChannelContract:
    """One channel's honest capabilities. ``max_note_seconds`` is 0 when notes are not accepted."""

    channel: ChannelType
    modes: frozenset[MediaMode]
    max_note_seconds: int = 0
    supports_barge_in: bool = False
    transcript_required: bool = True
    note: str = ""

    def accepts(self, mode: MediaMode) -> bool:
        return mode in self.modes

    def check_note(self, seconds: int) -> None:
        if not self.accepts(MediaMode.VOICE_NOTE):
            raise ValidationError(f"{self.channel.value} does not accept voice notes")
        if seconds <= 0:
            raise ValidationError("a voice note must have a positive duration")
        if seconds > self.max_note_seconds:
            raise ValidationError(
                f"{self.channel.value} voice notes are limited to {self.max_note_seconds}s"
            )


CHANNEL_CONTRACTS: Final[Mapping[ChannelType, ChannelContract]] = {
    ChannelType.WEB_VOICE: ChannelContract(
        channel=ChannelType.WEB_VOICE,
        modes=frozenset({MediaMode.REALTIME, MediaMode.TEXT}),
        supports_barge_in=True,
        note="browser voice: full duplex, the caller can interrupt",
    ),
    ChannelType.CHAT_VOICE: ChannelContract(
        channel=ChannelType.CHAT_VOICE,
        modes=frozenset({MediaMode.TEXT, MediaMode.VOICE_NOTE}),
        max_note_seconds=120,
        note="in-chat voice: notes inside a text thread",
    ),
    ChannelType.PSTN: ChannelContract(
        channel=ChannelType.PSTN,
        modes=frozenset({MediaMode.REALTIME}),
        supports_barge_in=True,
        note="a real call: the most expensive path, and the only one with a dial tone",
    ),
    ChannelType.WHATSAPP_VOICE: ChannelContract(
        channel=ChannelType.WHATSAPP_VOICE,
        modes=frozenset({MediaMode.VOICE_NOTE, MediaMode.TEXT}),
        max_note_seconds=120,
        note="WhatsApp caps a voice note; there is no barge-in over a finished recording",
    ),
    ChannelType.MOBILE: ChannelContract(
        channel=ChannelType.MOBILE,
        modes=frozenset({MediaMode.REALTIME, MediaMode.VOICE_NOTE, MediaMode.TEXT}),
        max_note_seconds=300,
        supports_barge_in=True,
        note="the app: realtime when foregrounded, notes when it is not",
    ),
}


def contract_for(channel: ChannelType) -> ChannelContract:
    """The contract, or a refusal. An unlisted channel never gets a default that grants audio."""
    contract = CHANNEL_CONTRACTS.get(channel)
    if contract is None:
        raise ValidationError(f"{channel.value} has no voice contract")
    return contract
