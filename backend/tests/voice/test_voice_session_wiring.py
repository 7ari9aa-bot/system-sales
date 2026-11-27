"""من إعدادات المحل لحد أول فريم في الجلسة: اللهجة والصوت لازم يوصلوا، والـtenant مايوصلش."""

from __future__ import annotations

from typing import Any

from app.modules.voice.application.voice_profile import (
    ArabicDialect,
    Presentation,
    ShopVoiceSettings,
    resolve_voice_profile,
    session_start_config,
)
from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveProvider


class RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def recv_event(self) -> dict[str, Any]:
        return {"type": "session.started", "session": {"id": "live_wired"}}

    async def close(self) -> None:
        return None


async def _start(settings: ShopVoiceSettings) -> dict[str, Any]:
    transport = RecordingTransport()
    provider = GptLiveProvider(
        GptLiveConfig(api_key="vck_test", voice="marin"), lambda _c: transport
    )
    profile = resolve_voice_profile(settings)
    await provider.create_session(session_start_config(profile))
    return transport.sent[0]["session"]


class TestTheWiredFrame:
    async def test_an_egyptian_shop_starts_with_the_egyptian_instruction(self) -> None:
        session = await _start(ShopVoiceSettings(country_code="EG", shop_name="محل النور"))
        assert session["audio"]["output"]["voice"] == "marin"
        assert "المصري" in session["instructions"]
        assert "متقولش" in session["instructions"]
        assert "محل النور" in session["instructions"]
        assert "مش صوت عربي أصلي" in session["instructions"]

    async def test_the_shops_chosen_voice_reaches_the_frame(self) -> None:
        session = await _start(
            ShopVoiceSettings(country_code="EG", voice_id="nuri", dialect=ArabicDialect.GULF)
        )
        assert session["audio"]["output"]["voice"] == "nuri"
        assert "الخليجية" in session["instructions"]

    async def test_a_presentation_choice_reaches_the_frame(self) -> None:
        session = await _start(ShopVoiceSettings(presentation=Presentation.MASCULINE))
        assert session["audio"]["output"]["voice"] == "meridian"

    async def test_an_english_shop_gets_no_arabic_block(self) -> None:
        session = await _start(
            ShopVoiceSettings(country_code="GB", language="en", shop_name="Nile Coffee")
        )
        assert "المصري" not in session["instructions"]
        assert session["instructions"] == "اسم المحل: Nile Coffee."

    async def test_the_frame_still_carries_no_tenant_and_no_persona(self) -> None:
        session = await _start(ShopVoiceSettings(country_code="EG"))
        flat = repr(session)
        assert "tenant" not in flat
        assert "persona" not in flat
        assert "merchant_assistant" not in flat
