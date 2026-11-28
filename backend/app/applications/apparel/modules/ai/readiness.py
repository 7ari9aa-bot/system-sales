"""Multimodal readiness — make 'OFF' visible at startup (voice-in, photos-in).

Every one of these features is built and gated, and each one goes DARK in a
deployment whose credential is simply absent. A dark feature must SAY SO when
the process boots — a WARNING in the operator's own logs — because
fail-closed-without-a-signpost looks identical to "the model is bad" and sends
the owner debugging the wrong thing.

- Voice notes without an STT key: stored, delivered, and answered with a
  "please type it" state — the customer's actual words are never heard.
- Customer photos without a scanner (ADR-062): the scan gate refuses to mint a
  provider URL, so vision never runs — by design; the signpost is what is new.
- A scanner WITHOUT the vision providers: photos get scanned and STILL never
  matched — the most confusing half-configured state of all, named explicitly.
- TTS is deliberately unwired (v1: text replies only) and is therefore NOT a
  warning — a key there enables a future feature, it does not un-break one.

Pure function of settings: no I/O and no providers, so a test asserts the exact
warnings a given configuration produces.
"""

from __future__ import annotations

from typing import Any

_ENABLED = ("1", "true", "yes", "on")


def _set(value: Any) -> bool:
    return bool((value or "").strip())


def multimodal_readiness(settings: Any) -> tuple[dict[str, bool], list[str]]:
    """(configured flags, startup warnings) for voice and customer photos."""
    configured = {
        "voice_in_stt": _set(getattr(settings, "stt_api_key", None)),
        "voice_in_omni": bool(getattr(settings, "ai_voice_audio_input", False)),
        "images_scanner": bool(getattr(settings, "media_scanner_configured", False)),
        "images_embedding": _set(getattr(settings, "ai_embedding_vision_api_key", None)),
        "images_reranker": _set(getattr(settings, "ai_reranker_api_key", None)),
        "voice_out_tts": _set(getattr(settings, "tts_api_key", None)),
    }

    configured["voice_in_pipeline"] = configured["voice_in_stt"] or configured["voice_in_omni"]

    warnings: list[str] = []
    if not configured["voice_in_stt"] and not configured["voice_in_omni"]:
        warnings.append(
            "voice notes will be acknowledged but NEVER understood — enable direct Omni audio "
            "(AI_VOICE_AUDIO_INPUT=true with a verified omni model_configs alias) or set "
            f"AI_STT_API_KEY (model: {getattr(settings, 'ai_stt_model', 'whisper-1')})"
        )
    if not configured["images_scanner"]:
        warnings.append(
            "customer photos will be acknowledged but NOT analyzed — no media scanner is "
            "configured (ADR-062 gate stays closed); run a clamd container beside the API and "
            "set MEDIA_SCANNER_HOST / MEDIA_SCANNER_PORT"
        )
    if configured["images_scanner"] and not (
        configured["images_embedding"] and configured["images_reranker"]
    ):
        warnings.append(
            "the media scanner is configured but the vision providers are not — photos will be "
            "scanned and STILL never matched; set AI_EMBEDDING_VISION_API_KEY and "
            "AI_RERANKER_API_KEY, then run scripts/index_product_images.py"
        )
    if (
        configured["images_embedding"]
        and configured["images_reranker"]
        and not configured["images_scanner"]
    ):
        warnings.append(
            "the vision providers are configured but the media scanner is not — the ADR-062 gate "
            "refuses to mint URLs, so nothing will ever reach them; set MEDIA_SCANNER_HOST/"
            "MEDIA_SCANNER_PORT"
        )

    # Voice-out is a roadmap item, not a regression: a TTS key enables replies
    # as audio once the reply path is wired, it does not fix anything broken.
    # It therefore gets a flag but never a warning line.
    configured["voice_out_tts_wired"] = False

    for flag in ("voice_in_pipeline", "images_scanner", "images_embedding", "images_reranker"):
        if not configured[flag]:
            warnings.append(f"multimodal flag {flag}: OFF")

    return configured, warnings
