"""Prove the client-delegation loop against the real gateway, not a fake transport.

What this measures, on one live GPT-Live session:

1. that the model delegates instead of answering a sales question itself;
2. that the transcript we assemble is what the turn runner receives;
3. that our answer travels back as ``session.commentary.append``;
4. that the model then SPEAKS that answer (its output transcript carries it).

Everything here is the shipped code: GptLiveProvider, the real websocket
transport, TranscriptBuffer and ClientDelegationService. Only the turn runner is
a stub, because the point is the protocol, not the database.

Usage:  python scripts/live_delegation_probe.py
Needs:  GPT_LIVE_API_KEY (or VERCEL_API_TOKEN_3), ffmpeg, gTTS.
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.voice.application.client_delegation import ClientDelegationService
from app.modules.voice.application.live_loop import TranscriptBuffer
from app.modules.voice.runtime import gpt_live_transport
from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider

QUESTION = "كام مبيعات النهاردة يا عم؟"
ANSWER = "مبيعات النهاردة اتناشر ألف وأربعمية جنيه."
INSTRUCTIONS = (
    "أنت مساعد متجر بيبيع بالعربي المصري. أي سؤال فيه أرقام أو مبيعات أو أسعار "
    "لازم تحوّله للباك إند وماتجاوبش من دماغك، واستنى الإجابة واقراها للعميل."
)


def arabic_pcm(text: str) -> bytes:
    """Speak Arabic and return PCM16 24kHz mono, the format the session asked for."""
    from gtts import gTTS

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "q.mp3")
        gTTS(text=text, lang="ar").save(mp3)
        out = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "quiet",
                "-i",
                mp3,
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "24000",
                "-",
            ],
            capture_output=True,
            check=True,
        )
        return out.stdout


async def main() -> int:
    key = (os.environ.get("GPT_LIVE_API_KEY") or os.environ.get("VERCEL_API_TOKEN_3") or "").strip()
    if not key:
        print("no gateway key in the environment")
        return 2
    config = GptLiveConfig(
        api_key=key,
        url=os.environ.get("GPT_LIVE_URL", "wss://ai-gateway.vercel.sh/v1/live/sessions"),
        model=os.environ.get("GPT_LIVE_MODEL", "openai/gpt-live-1.1"),
        voice=os.environ.get("GPT_LIVE_VOICE", "marin"),
    )

    provider = GptLiveProvider(config, gpt_live_transport.connect)
    heard: list[tuple[str, str]] = []

    async def turn_runner(request) -> str:
        heard.append((request.transcript, request.idempotency_key))
        return ANSWER

    delegations = ClientDelegationService(provider, turn_runner)
    session = await provider.create_session({"voice": config.voice, "instructions": INSTRUCTIONS})
    print(f"session: {session}")

    pcm = arabic_pcm(QUESTION)
    print(f"caller audio: {len(pcm)} bytes pcm16/24k for {QUESTION!r}")

    counts: Counter[str] = Counter()
    said_in: list[str] = []
    said_out: list[str] = []
    audio_out = 0
    buffer = TranscriptBuffer()
    outcome = "no delegation"

    frame = 4800  # 100ms at 24kHz mono
    for start in range(0, len(pcm), frame):
        await provider.stream_audio(session, pcm[start : start + frame])
        await asyncio.sleep(0.1)

    started = asyncio.get_running_loop().time()
    deadline = started + 25
    extensions = 0
    while asyncio.get_running_loop().time() < deadline:
        try:
            event = await asyncio.wait_for(provider.next_event(session), timeout=8)
        except TimeoutError:
            break
        kind = str(event.get("type") or "?")
        counts[kind] += 1
        if kind == "session.input_transcript.delta":
            buffer.append(str(event.get("delta") or ""))
            said_in.append(str(event.get("delta") or ""))
        elif kind == "session.output_transcript.delta":
            said_out.append(str(event.get("delta") or ""))
        elif kind == "session.output_audio.delta":
            audio_out += len(base64.b64decode(str(event.get("delta") or "")))
        elif kind == "session.delegation.created":
            outcome = await delegations.on_event(session, event, transcript=buffer.take())
            print(f"delegation: {outcome}")
        elif kind == "session.closed":
            break
        now = asyncio.get_running_loop().time()
        answered = any(word in "".join(said_out) for word in ("اتناشر", "ألف"))
        if heard and answered and extensions < 2:
            # The model has started speaking our answer; read a little longer, twice at most.
            extensions += 1
            deadline = min(now + 4, started + 40)

    try:
        await asyncio.wait_for(provider.close_session(session), timeout=8)
    except (TimeoutError, Exception) as exc:  # noqa: BLE001 - a close that hangs is not a result
        print("close:", type(exc).__name__)

    print("events:", dict(counts))
    print("heard by the model:", "".join(said_in).strip())
    print("turn runner got:", heard)
    print("model said:", "".join(said_out).strip())
    print("model audio bytes:", audio_out)
    spoke_answer = any(word in "".join(said_out) for word in ("اتناشر", "ألف"))
    print("RESULT delegation:", outcome)
    print("RESULT spoke our answer:", spoke_answer)
    ok = outcome == "answered" and heard and spoke_answer
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
