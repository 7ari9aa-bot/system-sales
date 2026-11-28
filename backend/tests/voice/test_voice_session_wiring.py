"""من إعدادات المحل لحد أول فريم في الجلسة: اللهجة والصوت لازم يوصلوا، والـtenant مايوصلش."""

from __future__ import annotations

from typing import Any

from app.modules.voice.application.voice_profile import (
    BASE_CONTRACT,
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
        assert session["instructions"].startswith(BASE_CONTRACT)
        assert session["instructions"].endswith("اسم المحل: Nile Coffee.")

    async def test_the_frame_still_carries_no_tenant_and_no_persona(self) -> None:
        session = await _start(ShopVoiceSettings(country_code="EG"))
        flat = repr(session)
        assert "tenant" not in flat
        assert "persona" not in flat
        assert "merchant_assistant" not in flat


class TestTheContractEveryCallCarries:
    """العقد اللي لازم يوصل مع أي لهجة وأي لغة: الوكيل بيفوّض، مش بيخترع أرقام."""

    def test_the_arabic_prompt_forbids_inventing_numbers(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="EG", shop_name="محل النور"))
        assert "BASE_CONTRACT" not in profile.instructions  # النص نفسه، مش اسم الثابت
        assert "لازم يتفوّض" in profile.instructions
        assert "متخمّنش رقم" in profile.instructions
        assert "اسم المحل: محل النور." in profile.instructions

    def test_the_english_shop_keeps_the_same_contract(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="GB", language="en"))
        assert "لازم يتفوّض" in profile.instructions
        assert "مفيش عندك أي بيانات" in profile.instructions
        # ومن غير لهجة عربية تتحقن غلط
        assert "المصري" not in profile.instructions

    def test_the_contract_comes_first_so_the_dialect_refines_it(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="SA"))
        assert profile.instructions.startswith("أنت المساعد الصوتي")
        contract_at = profile.instructions.index("أنت المساعد الصوتي")
        dialect_at = profile.instructions.index("الخليجية")
        assert contract_at < dialect_at


class TestThePromptIsReadFromTheShop:
    async def test_a_real_tenant_row_becomes_one_instruction_block(self) -> None:
        import uuid

        from app.modules.voice.application.shop_voice import load_shop_voice_config

        tenant_id = uuid.uuid4()

        class _Rows:
            def first(self):
                return ("محل النور", "SA", "gulf")

        class _Session:
            async def execute(self, _statement):
                return _Rows()

        config = await load_shop_voice_config(_Session(), tenant_id)
        assert config["voice"] == "marin"
        assert "الخليجية" in config["instructions"]
        assert "اسم المحل: محل النور." in config["instructions"]
        assert "لازم يتفوّض" in config["instructions"]

    async def test_a_missing_tenant_still_starts_a_call_instead_of_crashing(self) -> None:
        import uuid

        from app.modules.voice.application.shop_voice import load_shop_voice_config

        class _Rows:
            def first(self):
                return None

        class _Session:
            async def execute(self, _statement):
                return _Rows()

        config = await load_shop_voice_config(_Session(), uuid.uuid4())
        assert config["voice"] == "marin"
        assert "لازم يتفوّض" in config["instructions"]
        # ومفيش اسم محل مخترع
        assert "اسم المحل" not in config["instructions"]

    async def test_the_dialect_column_can_be_a_value_we_do_not_know(self) -> None:
        import uuid

        from app.modules.voice.application.shop_voice import load_shop_voice_config

        class _Rows:
            def first(self):
                return ("متجر", "EG", "nubian")

        class _Session:
            async def execute(self, _statement):
                return _Rows()

        config = await load_shop_voice_config(_Session(), uuid.uuid4())
        # البلد بيشتغل بدل قيمة مش معروفة، والجلسة ما بتسقطش
        assert "المصري" in config["instructions"]
