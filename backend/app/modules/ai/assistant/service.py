"""The single door a turn walks through, text or spoken.

Everything that makes a turn a turn — which thread, which agent and version,
which history, which answer row — is decided here once. The execution itself is
the existing agent runtime (``run_chat_turn`` -> ``run_sales_analysis`` ->
``AgentRunner``): voice does not get a second brain, a second set of sales tools
or a second conversation, only a second way of arriving.
"""

from __future__ import annotations

import logging

from app.core.errors import ValidationError
from app.modules.ai.assistant.contracts import (
    MODALITIES,
    AssistantTurnInput,
    AssistantTurnResult,
)

logger = logging.getLogger(__name__)


class UnsupportedModality(ValidationError):
    """The carrier is not one this runtime answers."""

    code = "unsupported_modality"
    default_message = "unknown turn modality"


class ThreadMismatch(ValidationError):
    """The turn names a conversation other than the one it was loaded with."""

    code = "thread_mismatch"
    default_message = "the turn names a different conversation than the one loaded"


class AssistantTurnService:
    """One turn, one conversation, one runtime — for every modality."""

    async def run(self, session, ctx, thread, turn: AssistantTurnInput) -> AssistantTurnResult:
        """Answer one turn on ``thread`` and say which conversation answered.

        The thread is the authority: it already carries the agent the shop chose
        and the message sequence the history is built from. A turn that names a
        different thread than the one it was loaded with is refused rather than
        quietly answered on the wrong conversation.
        """
        if turn.modality not in MODALITIES:
            raise UnsupportedModality(f"unknown turn modality {turn.modality!r}")
        if turn.thread_id != thread.id or thread.tenant_id != turn.tenant_id:
            # get_thread already scopes to the tenant; this is the belt to that
            # brace, because a voice session can be resumed by another request.
            raise ThreadMismatch()

        # Imported here: chat.turns owns the execution and imports this package
        # through the router, so a module-level import would be a cycle.
        from app.modules.ai.chat.turns import run_chat_turn

        message = await run_chat_turn(session, ctx, thread)
        logger.info(
            "assistant.turn modality=%s thread=%s message=%s voice_session=%s",
            turn.modality,
            thread.id,
            message.id,
            turn.voice_session_id,
        )
        return AssistantTurnResult(
            thread_id=thread.id,
            agent_id=getattr(thread, "agent_id", None),
            assistant_message_id=message.id,
            content=message.content or "",
            status=message.status,
            modality=turn.modality,
            message=message,
        )


__all__ = [
    "AssistantTurnService",
    "AssistantTurnInput",
    "AssistantTurnResult",
    "ThreadMismatch",
    "UnsupportedModality",
]
