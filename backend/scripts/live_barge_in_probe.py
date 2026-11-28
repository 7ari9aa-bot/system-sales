"""Barge-in measured on a real GPT-Live session — two ways, because they are not the same.

1. **The button.** Once the model's audio is flowing we call ``interrupt()`` and keep
   reading frames: the sink must receive nothing more while the socket stays open.
2. **The voice.** The caller says something over the answer instead of pressing anything.
   No ``interrupt()`` call at all: the caller's own words arrive as
   ``session.input_transcript.delta`` and that frame alone must stop the speaker. This is
   the one the owner hears as "the assistant talks over me until I finish my sentence",
   and it is the case the code cannot prove on its own — a unit test proves the frame is
   handled, only the real gateway proves the frame is what arrives when a person speaks.

That is the whole guarantee in both cases: we cannot make the model stop talking, we can
stop playing it.

Usage:  python scripts/live_barge_in_probe.py [--voice]
        (the key comes from GPT_LIVE_API_KEY or VERCEL_API_TOKEN_3)
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.platform.voice.application.live_loop import LiveCallLoop
from app.platform.voice.runtime import gpt_live_transport
from app.platform.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider

INSTRUCTIONS = "أنت مساعد متجر بالعربي المصري. اتكلم بصوت عالي وواضح."


class NoDelegations:
    async def on_event(self, session_id, event, *, transcript):
        return "answered"


async def _speak(loop, text: str) -> int:
    """Send a spoken prompt as PCM16/24k, the way the browser sends a caller's microphone."""
    import subprocess
    import tempfile

    from gtts import gTTS

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "q.mp3")
        gTTS(text=text, lang="ar").save(mp3)
        pcm = subprocess.run(
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
        ).stdout
    for start in range(0, len(pcm), 4800):
        await loop.push_audio(pcm[start : start + 4800])
        await asyncio.sleep(0.1)
    return len(pcm)


async def _voice_barge_in(provider, config) -> int:
    """The caller talks over the answer. Nothing presses anything.

    Measured: frames played after the caller's FIRST transcript fragment must be zero, and
    the loop must report ``barged_in``. If the provider only flushes the caller's words
    after the answer has finished, this probe cannot measure it and says so rather than
    passing on an empty window.
    """
    played: list[int] = []
    loop = LiveCallLoop(provider, NoDelegations(), audio_sink=lambda pcm: played.append(len(pcm)))
    await loop.start(
        voice_session_id="probe-voice", config={"voice": config.voice, "instructions": INSTRUCTIONS}
    )

    await _speak(loop, "احكي لي حكاية طويلة عن القاهرة")
    deadline = asyncio.get_running_loop().time() + 20
    while not played and asyncio.get_running_loop().time() < deadline:
        try:
            await asyncio.wait_for(loop.pump(), timeout=8)
        except TimeoutError:
            break
    if not played:
        print("no model audio arrived, so there was nothing to talk over")
        return 2
    before = len(played)

    # The caller interrupts with their voice: real audio, no interrupt() call.
    await _speak(loop, "استنى استنى، سؤال تاني")

    barged = 0
    after_frames = 0
    deadline = asyncio.get_running_loop().time() + 12
    while asyncio.get_running_loop().time() < deadline:
        try:
            outcome = await asyncio.wait_for(loop.pump(), timeout=6)
        except TimeoutError:
            break
        if outcome == "barged_in":
            barged += 1
        elif outcome == "audio":
            after_frames += 1
        if barged and after_frames:
            break

    try:
        await asyncio.wait_for(loop.close(), timeout=8)
    except TimeoutError:
        pass

    print(
        f"voice barge-in: frames before {before}, barged_in frames {barged}, "
        f"played after the caller spoke {after_frames}, muted={loop.muted}"
    )
    if not barged:
        print("the provider sent no caller transcript while the answer played — not measured")
        return 2
    ok = after_frames == 0 and loop.muted is True
    print("VOICE RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


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
    played: list[int] = []
    loop = LiveCallLoop(provider, NoDelegations(), audio_sink=lambda pcm: played.append(len(pcm)))
    provider_session = await loop.start(
        voice_session_id="probe", config={"voice": config.voice, "instructions": INSTRUCTIONS}
    )
    print(f"session: {provider_session}")

    if "--voice" in sys.argv[1:]:
        return await _voice_barge_in(provider, config)

    # The model speaks first: one short spoken prompt is enough to get audio flowing.
    await _speak(loop, "قولي أهلاً باللهجة المصرية")

    # Wait for the first model audio, then interrupt mid-utterance.
    deadline = asyncio.get_running_loop().time() + 20
    while not played and asyncio.get_running_loop().time() < deadline:
        try:
            await asyncio.wait_for(loop.pump(), timeout=8)
        except TimeoutError:
            break
    before = len(played)
    await loop.interrupt()
    print(f"interrupted after {before} audio frames, muted={loop.muted}")

    after_frames = 0
    muted = 0
    deadline = asyncio.get_running_loop().time() + 12
    while asyncio.get_running_loop().time() < deadline:
        try:
            outcome = await asyncio.wait_for(loop.pump(), timeout=6)
        except TimeoutError:
            break
        if outcome == "audio":
            after_frames += 1
        elif outcome == "muted":
            muted += 1
        if muted >= 5:
            break

    try:
        await asyncio.wait_for(loop.close(), timeout=8)
    except TimeoutError:
        pass

    print(
        f"frames played before: {before}, played after interrupt: {after_frames}, dropped: {muted}"
    )
    ok = before > 0 and after_frames == 0 and muted > 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
