"""The two guards that cost money, measured on a real GPT-Live session.

1. A delegation delivered twice runs the turn ONCE (a redelivery must not buy the
   same answer twice).
2. After the call is closed, audio is refused (usage ends with the call, it does
   not keep streaming into a session nobody is paying attention to).

Both are unit-tested against a fake transport; this measures them against the
gateway, because the redelivery and the close are the gateway's behaviour, not
ours.

Usage:  python scripts/live_call_guards_probe.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.voice.application.client_delegation import ClientDelegationService
from app.modules.voice.application.live_loop import TranscriptBuffer
from app.modules.voice.runtime import gpt_live_transport
from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider

QUESTION = "كام مبيعات النهاردة يا عم؟"
ANSWER = "مبيعات النهاردة اتناشر ألف وأربعمية جنيه."
INSTRUCTIONS = (
    "أنت مساعد متجر بالعربي المصري. أي سؤال فيه أرقام أو مبيعات حوّله للباك إند "
    "وماتجاوبش من دماغك، واستنى الإجابة واقراها للعميل."
)


def arabic_pcm(text: str) -> bytes:
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
    runs: list[str] = []

    async def turn_runner(transcript: str, idempotency_key: str) -> str:
        runs.append(idempotency_key)
        return ANSWER

    delegations = ClientDelegationService(provider, turn_runner)
    session = await provider.create_session({"voice": config.voice, "instructions": INSTRUCTIONS})
    print(f"session: {session}")

    pcm = arabic_pcm(QUESTION)
    for start in range(0, len(pcm), 4800):
        await provider.stream_audio(session, pcm[start : start + 4800])
        await asyncio.sleep(0.1)

    buffer = TranscriptBuffer()
    outcomes: list[str] = []
    deadline = asyncio.get_running_loop().time() + 25
    while asyncio.get_running_loop().time() < deadline and len(outcomes) < 2:
        try:
            event = await asyncio.wait_for(provider.next_event(session), timeout=8)
        except TimeoutError:
            break
        kind = str(event.get("type") or "")
        if kind == "session.input_transcript.delta":
            buffer.append(str(event.get("delta") or ""))
        elif kind == "session.delegation.created":
            transcript = buffer.take()
            # The SAME event twice, exactly as a redelivery would arrive.
            outcomes.append(await delegations.on_event(session, event, transcript=transcript))
            outcomes.append(await delegations.on_event(session, event, transcript=transcript))

    try:
        await asyncio.wait_for(provider.close_session(session), timeout=8)
    except TimeoutError:
        pass

    refused_after_close = False
    try:
        await provider.stream_audio(session, b"\x00\x00" * 480)
    except Exception as exc:  # noqa: BLE001 - the type is what we are measuring
        refused_after_close = type(exc).__name__

    print("delegation outcomes:", outcomes)
    print("turn runs:", runs)
    duplicate_once = outcomes[:2] == ["answered", "duplicate"] and len(runs) == 1
    print("RESULT one turn per delegation:", duplicate_once)
    print("RESULT audio after close:", refused_after_close or "ACCEPTED")
    ok = duplicate_once and refused_after_close
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
