"""Barge-in measured on a real GPT-Live session.

The model is asked something it answers out loud. Once its audio is flowing we
interrupt, and then keep reading frames: the sink must receive nothing more while
the socket stays open. That is the whole guarantee — we cannot make the model stop
talking, we can stop playing it.

Usage:  python scripts/live_barge_in_probe.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.voice.application.live_loop import LiveCallLoop
from app.modules.voice.runtime import gpt_live_transport
from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider

INSTRUCTIONS = "أنت مساعد متجر بالعربي المصري. اتكلم بصوت عالي وواضح."


class NoDelegations:
    async def on_event(self, session_id, event, *, transcript):
        return "answered"


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

    # The model speaks first: one short spoken prompt is enough to get audio flowing.
    import subprocess
    import tempfile

    from gtts import gTTS

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "q.mp3")
        gTTS(text="قولي أهلاً باللهجة المصرية", lang="ar").save(mp3)
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
