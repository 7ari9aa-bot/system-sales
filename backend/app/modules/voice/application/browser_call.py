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

Honest gap, stated here rather than discovered later: a stream session has a
tenant from its ticket but no resolved capability scopes yet. Permissions parity
is a launch requirement, so the runner refuses out loud instead of faking a
permission it was never given.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.modules.voice.application.client_delegation import ClientDelegationService
from app.modules.voice.application.live_loop import LiveCallLoop
from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider, GptLiveUnavailable
from app.modules.voice.runtime.gpt_live_transport import transport_factory

AudioSender = Callable[[bytes], Awaitable[None]]


async def build_browser_call(
    *, session_id, tenant_id, send_audio: AudioSender, config: dict | None = None
) -> LiveCallLoop:
    """Open the gateway session and return a loop already started on it."""
    live_config = GptLiveConfig.from_settings()
    if live_config is None:
        raise GptLiveUnavailable("no gateway key is configured for voice")

    provider = GptLiveProvider(live_config, transport_factory=transport_factory)
    delegations = ClientDelegationService(provider, _turn_runner(session_id, tenant_id))
    loop = LiveCallLoop(
        provider,
        delegations,
        audio_sink=_sync_sink(send_audio),
    )
    await loop.start(voice_session_id=session_id, config=config or {})
    return loop


def _turn_runner(session_id, tenant_id):
    """Answer a delegation with the same assistant turn the text route runs.

    The turn itself is ``run_voice_turn`` — the same function the text path
    reaches through ``AssistantTurnService``. What is missing is not the brain but
    the AUTHORITY: a stream session has a tenant from its ticket, and a tenant is
    not a permission. Resolving the caller's capability scopes for a websocket is
    the remaining piece (permissions parity is a launch requirement, so it is not
    being faked here), and until it exists this runner refuses out loud: the
    delegation is answered with the failure note instead of a made-up reply.
    """

    async def run(transcript: str, idempotency_key: str) -> str:
        raise GptLiveUnavailable("a stream session has no resolved capability scopes yet")

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
