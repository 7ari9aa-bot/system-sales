"""One browser call: the socket to GPT-Live, wired to the assistant's turn.

The browser never holds the gateway key. It streams PCM to us over a websocket
(``/voice/sessions/{id}/stream``) and this module is what sits on the other side:
a real provider over the real gateway, a ``LiveCallLoop`` that pumps audio both
ways, and ``ClientDelegationService`` that answers the model's delegations with
the same assistant turn the text path runs.

What the caller said is captured by the loop itself: the gateway sends
``session.input_transcript.delta`` fragments (documented in the live-delegation
guide), and ``TranscriptBuffer`` keeps the pending question apart from a bounded
history, so a delegation is answered with the words that were actually spoken.

Permissions are not a gap: the caller is resolved through ``build_tenant_context``
— the same membership, lifecycle, role-permission and RLS code every HTTP request
uses — so a spoken turn is governed exactly like a typed one.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from app.platform.voice.application.client_delegation import (
    ClientDelegationService,
    TurnRequest,
)
from app.platform.voice.application.live_loop import LiveCallLoop
from app.platform.voice.application.spoken_turns import TurnLedger
from app.platform.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider, GptLiveUnavailable
from app.platform.voice.runtime.gpt_live_transport import transport_factory

AudioSender = Callable[[bytes], Awaitable[None]]

#: The path a streamed turn is evaluated under. It is not a recovery path, so a
#: suspended shop cannot keep talking through an already-open socket.
STREAM_PATH = "/api/v1/voice/sessions/stream"


async def build_browser_call(
    *, session_id, tenant_id, user_id, send_audio: AudioSender, config: dict | None = None
) -> LiveCallLoop:
    """Open the gateway session and return a loop already started on it."""
    live_config = GptLiveConfig.from_settings()
    if live_config is None:
        raise GptLiveUnavailable("no gateway key is configured for voice")

    provider = GptLiveProvider(live_config, transport_factory=transport_factory)
    # ONE ledger for the call: the delegation begins each turn on it, the assistant turn reads it
    # to see whether that turn is still wanted, and the loop drops the turn on a barge-in.
    ledger = TurnLedger()
    delegations = ClientDelegationService(
        provider,
        _turn_runner(session_id, tenant_id, user_id, ledger),
        call_id=str(session_id),
        ledger=ledger,
    )
    loop = LiveCallLoop(
        provider,
        delegations,
        audio_sink=_sync_sink(send_audio),
    )
    await loop.start(voice_session_id=session_id, config=config or {})
    return loop


def _turn_runner(session_id, tenant_id, user_id, ledger):
    """Answer a delegation with the same assistant turn the text route runs.

    The caller was resolved once, over HTTP, when the ticket was minted; here that
    identity is resolved AGAIN through ``build_tenant_context`` — the same
    membership, lifecycle, role-permission and RLS code the rest of the API uses —
    so a spoken turn is governed by the same rules as a typed one and not by a
    second, weaker copy of them. A user who lost access between the ticket and the
    answer is refused by that same gate.

    The turn arrives with the id the delegation minted for it and goes down the
    same ledger, so the answer can be recognised as stale before it is spoken.
    """

    async def run(request: TurnRequest) -> str:
        if not (request.transcript or "").strip():
            return ""
        from app.core.db import get_sessionmaker
        from app.platform.identity.deps import build_tenant_context_for_user
        from app.platform.voice.application.assistant_turn import run_voice_turn

        tenant_uuid = uuid.UUID(str(tenant_id))
        async with get_sessionmaker()() as session:
            ctx = await build_tenant_context_for_user(
                session,
                user_id=uuid.UUID(str(user_id)),
                tenant_id=tenant_uuid,
                path=STREAM_PATH,
            )
            result = await run_voice_turn(
                session,
                ctx,
                session_id=session_id,
                text=request.transcript,
                idempotency_key=request.idempotency_key,
                turn=request.turn,
                ledger=ledger,
            )
            await session.commit()
            # A superseded answer is empty already; saying so twice costs nothing and keeps the
            # rule in one place for a caller that only reads the text.
            return "" if result.superseded else str(result.content or "")

    return run


def _sync_sink(send_audio: AudioSender):
    """The loop hands audio to a sync sink; the websocket send is async.

    The frame is queued on the running loop instead of blocking the pump, so one
    slow client cannot stall the call's audio path.
    """
    import asyncio

    def sink(pcm: bytes) -> None:
        try:
            asyncio.get_running_loop().create_task(send_audio(pcm))
        except RuntimeError:  # pragma: no cover - no loop means no call
            pass

    return sink
