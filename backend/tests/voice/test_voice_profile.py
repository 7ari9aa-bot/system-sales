"""The voice and the dialect: chosen from the shop's own settings, never guessed at runtime."""

from __future__ import annotations

import pytest

from app.platform.voice.application.voice_profile import (
    BASE_CONTRACT,
    VOICE_CATALOG,
    VOICES_BY_ID,
    ArabicDialect,
    Presentation,
    ShopVoiceSettings,
    resolve_voice_profile,
)


class TestDialectFromCountry:
    def test_an_egyptian_shop_speaks_egyptian(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="EG"))
        assert profile.dialect is ArabicDialect.EGYPTIAN
        assert "المصري" in profile.instructions
        # The instruction has to forbid the thing the model would otherwise drift into.
        assert "متقولش" in profile.instructions
        assert "دلوقتي" in profile.instructions

    def test_a_gulf_shop_speaks_gulf(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="sa"))
        assert profile.dialect is ArabicDialect.GULF
        assert "الخليجية" in profile.instructions

    def test_a_moroccan_shop_speaks_darija(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="MA"))
        assert profile.dialect is ArabicDialect.MOROCCAN
        assert "الدارجة" in profile.instructions

    def test_an_arabic_country_we_have_no_dialect_for_gets_clear_fus7a(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="IQ"))
        assert profile.dialect is ArabicDialect.MODERN_STANDARD
        assert "فصحى" in profile.instructions

    def test_an_explicit_dialect_beats_the_shops_country(self) -> None:
        profile = resolve_voice_profile(
            ShopVoiceSettings(country_code="EG", dialect=ArabicDialect.GULF)
        )
        assert profile.dialect is ArabicDialect.GULF
        assert "المصري" not in profile.instructions


class TestTheVoiceItself:
    def test_a_shop_with_no_preference_gets_the_models_default(self) -> None:
        assert resolve_voice_profile(ShopVoiceSettings()).voice_id == "marin"

    def test_a_presentation_preference_picks_a_matching_voice(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(presentation=Presentation.MASCULINE))
        assert VOICES_BY_ID[profile.voice_id].presentation is Presentation.MASCULINE

    def test_an_explicit_voice_wins(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(voice_id="nuri", language="de"))
        assert profile.voice_id == "nuri"
        assert profile.voice_is_native_for_language is True

    def test_an_unknown_voice_is_refused_rather_than_silently_replaced(self) -> None:
        with pytest.raises(ValueError):
            resolve_voice_profile(ShopVoiceSettings(voice_id="not-a-voice"))

    def test_no_voice_in_the_catalog_is_arabic(self) -> None:
        # The product must never claim a native Arabic voice exists while this is true.
        assert all(voice.language != "Arabic" for voice in VOICE_CATALOG)
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="EG"))
        assert profile.voice_is_native_for_language is False
        assert profile.needs_dialect_instruction is True
        assert "مش صوت عربي أصلي" in profile.instructions


class TestOtherLanguages:
    def test_an_english_shop_gets_no_arabic_instruction_at_all(self) -> None:
        profile = resolve_voice_profile(
            ShopVoiceSettings(country_code="GB", language="en", shop_name="Nile Coffee")
        )
        assert profile.dialect is None
        assert "المصري" not in profile.instructions
        # العقد بيفضل موجود لكل لغة، والمحل هو آخر سطر: مش نص عربي متسرّب، ده تعليمات
        # التفويض اللي من غيرها الموديل هيخترع أرقام.
        assert profile.instructions.startswith(BASE_CONTRACT)
        assert profile.instructions.endswith("اسم المحل: Nile Coffee.")

    def test_the_shop_name_travels_into_the_instructions(self) -> None:
        profile = resolve_voice_profile(ShopVoiceSettings(country_code="EG", shop_name="محل النور"))
        assert "محل النور" in profile.instructions
