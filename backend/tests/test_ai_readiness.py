"""The multimodal readiness report — 'OFF' must be visible, never silent.

The scanner gate (ADR-062) is fail-closed by design; the failure mode it
creates is a deployment where customer photos are politely acknowledged and
never analyzed, and nothing anywhere says why. These tests pin the report that
names every dark feature and the exact env var that turns it on.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.ai.readiness import multimodal_readiness


def _settings(**overrides):
    base = dict(
        stt_api_key="",
        ai_stt_model="whisper-1",
        media_scanner_configured=False,
        ai_embedding_vision_api_key="",
        ai_reranker_api_key="",
        tts_api_key="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_an_empty_deployment_names_every_dark_feature() -> None:
    configured, warnings = multimodal_readiness(_settings())

    assert configured["voice_in_stt"] is False
    assert configured["images_scanner"] is False
    assert configured["images_embedding"] is False
    assert configured["images_reranker"] is False

    joined = "\n".join(warnings)
    assert "AI_STT_API_KEY" in joined, "voice-off must name its env var"
    assert "MEDIA_SCANNER_HOST" in joined, "photos-off must name its env var"


def test_a_full_deployment_warns_about_nothing() -> None:
    configured, warnings = multimodal_readiness(
        _settings(
            stt_api_key="sk-stt",
            media_scanner_configured=True,
            ai_embedding_vision_api_key="sk-embed",
            ai_reranker_api_key="sk-rerank",
        )
    )

    operational = ("voice_in_stt", "images_scanner", "images_embedding", "images_reranker")
    assert all(configured[flag] for flag in operational)
    assert configured["voice_out_tts"] is False, "TTS is a roadmap item, not a deployment need"
    assert warnings == [], f"a fully configured deployment must be silent, got: {warnings}"


def test_the_half_configured_trap_is_named() -> None:
    """Scanner without vision providers: photos get scanned and STILL never
    matched — the most confusing state, so it gets its own explicit warning."""
    _configured, warnings = multimodal_readiness(
        _settings(media_scanner_configured=True)
    )
    joined = "\n".join(warnings)
    assert "scanned and STILL never matched" in joined
    assert "AI_EMBEDDING_VISION_API_KEY" in joined
    assert "scripts/index_product_images.py" in joined


def test_vision_providers_without_a_scanner_name_the_closed_gate() -> None:
    """Keys without the scanner: the ADR-062 gate refuses to mint URLs, so the
    providers would sit idle forever — the owner must hear WHICH gate."""
    _configured, warnings = multimodal_readiness(
        _settings(ai_embedding_vision_api_key="sk-embed", ai_reranker_api_key="sk-rerank")
    )
    joined = "\n".join(warnings)
    assert "ADR-062" in joined
    assert "MEDIA_SCANNER_HOST" in joined


def test_tts_is_a_roadmap_item_not_a_warning() -> None:
    """Voice-out is deliberately unwired (v1 replies are text): a TTS key
    enables a future feature, it does not un-break one — so its absence is
    never in the warning list."""
    _configured, warnings = multimodal_readiness(_settings())
    assert all("TTS" not in warning and "tts" not in warning for warning in warnings)
    assert "voice_out_tts_wired" in _configured


def test_off_flags_are_reported_individually() -> None:
    """Every dark flag is its own line, so an operator can tick them off."""
    _configured, warnings = multimodal_readiness(_settings())
    off_lines = [w for w in warnings if w.startswith("multimodal flag ")]
    assert any("voice_in_stt: OFF" in line for line in off_lines)
    assert any("images_scanner: OFF" in line for line in off_lines)
