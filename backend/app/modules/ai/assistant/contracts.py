"""What a turn IS, whatever carried it here.

A written question and a spoken one are the same turn with a different carrier.
So the carrier is a field, not a second set of contracts: one input, one result,
and the caller names the modality instead of inventing a parallel path with its
own idea of what a thread, an agent version or an answer is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

TEXT = "text"
LIVE_VOICE = "live_voice"

#: The carriers this runtime answers today. A voice note is not here on purpose:
#: it arrives as a file and is transcribed before it becomes a turn (see
#: ``voice/application/transcript_sync.py``), so by the time it reaches this
#: service it is already ``TEXT``.
MODALITIES = frozenset({TEXT, LIVE_VOICE})


@dataclass(frozen=True, slots=True)
class AssistantTurnInput:
    """One turn, addressed to the conversation it belongs to."""

    tenant_id: uuid.UUID
    thread_id: uuid.UUID
    modality: str = TEXT
    #: The voice session that carried this turn, when one did. It is a reference
    #: for the record, never an authority: the thread and the agent come from the
    #: conversation, so a caller cannot name its own brain.
    voice_session_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AssistantTurnResult:
    """One answer, with the identity of the conversation that produced it."""

    thread_id: uuid.UUID
    agent_id: uuid.UUID | None
    assistant_message_id: uuid.UUID
    content: str
    status: str
    modality: str
    #: The answer row itself, already on the caller's session: the API serialises
    #: it directly instead of re-reading what this service just wrote.
    message: object | None = None
