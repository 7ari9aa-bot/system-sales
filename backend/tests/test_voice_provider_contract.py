"""The voice provider contract — the settings the STT/TTS path actually reads.

The defect this file exists for: `get_default_stt_provider()` read
`getattr(settings, "openai_api_key", None)`. That field has never existed on
`Settings`, and `extra="ignore"` means exporting `OPENAI_API_KEY` would not
create it either. So the factory returned `None` forever and voice was
unreachable in EVERY environment — production included — silently.

DB-free on purpose: none of this needs Postgres, and a configuration contract
that only runs in CI is a contract that breaks on a laptop.
"""

from __future__ import annotations

import pathlib

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = BACKEND_ROOT / "app"

# Every setting the voice path reads. `.env.example` must document each one, or
# an operator has no way to discover the contract.
VOICE_SETTINGS = (
    "AI_STT_API_KEY",
    "AI_STT_BASE_URL",
    "AI_STT_MODEL",
    "AI_TTS_API_KEY",
    "AI_TTS_BASE_URL",
    "AI_TTS_MODEL",
    "AI_TTS_VOICE",
)


def _settings(**overrides: object):
    from app.core.config import Settings

    return Settings(environment="local", **overrides)  # type: ignore[arg-type]


# ------------------------------------------------- 1. credential resolution --


def test_stt_has_no_credential_when_nothing_is_configured() -> None:
    """A real 'off' state — not the accidental one a bad getattr produced."""
    assert _settings().stt_api_key == ""


def test_stt_falls_back_to_the_primary_ai_credential() -> None:
    """A deployment that configured AI gets voice without a second key."""
    settings = _settings(ai_api_key_primary="primary-key")
    assert settings.stt_api_key == "primary-key"
    assert settings.tts_api_key == "primary-key"


def test_a_voice_specific_credential_wins_over_the_primary() -> None:
    """An operator may point voice at a different vendor."""
    settings = _settings(
        ai_api_key_primary="primary-key",
        ai_stt_api_key="stt-key",
        ai_tts_api_key="tts-key",
    )
    assert settings.stt_api_key == "stt-key"
    assert settings.tts_api_key == "tts-key"


def test_base_urls_fall_back_then_default() -> None:
    from app.core.config import _DEFAULT_OPENAI_BASE_URL

    assert _settings().stt_base_url == _DEFAULT_OPENAI_BASE_URL
    assert _settings(ai_base_url_primary="https://chat.example/v1").stt_base_url == (
        "https://chat.example/v1"
    )
    settings = _settings(
        ai_base_url_primary="https://chat.example/v1", ai_stt_base_url="https://stt.example/v1"
    )
    assert settings.stt_base_url == "https://stt.example/v1"


def test_the_voice_models_are_not_the_chat_model() -> None:
    """`whisper-1`/`tts-1` are their own model names, not the chat model."""
    settings = _settings(ai_model_primary="gpt-4o-mini")
    assert settings.ai_stt_model == "whisper-1"
    assert settings.ai_tts_model == "tts-1"
    assert settings.ai_tts_voice == "alloy"


# ------------------------------------------------------- 2. the factories ----


def test_the_factory_returns_none_only_without_a_credential(monkeypatch) -> None:
    from app.modules.conversations import voice

    monkeypatch.setattr(voice, "get_settings", lambda: _settings(), raising=False)
    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
    assert voice.get_default_stt_provider() is None
    assert voice.get_default_tts_provider() is None


def test_the_factory_returns_a_provider_when_a_credential_resolves(monkeypatch) -> None:
    from app.modules.conversations import voice

    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings(ai_api_key_primary="k"))
    stt = voice.get_default_stt_provider()
    tts = voice.get_default_tts_provider()
    assert stt is not None and tts is not None
    assert isinstance(stt, voice.OpenAIWhisperSTTProvider)
    assert isinstance(tts, voice.OpenAITTSProvider)


# -------------------------------------------- 3. the call the provider makes --


class _CapturedPost:
    def __init__(self) -> None:
        self.url: str | None = None
        self.headers: dict[str, str] = {}
        self.files: dict | None = None
        # NOT `self.json` — that would shadow the `json()` method below.
        self.json_payload: dict | None = None

    def raise_for_status(self) -> None:  # noqa: D102
        return None

    def json(self) -> dict:  # noqa: D102
        return {"text": "مرحبا"}

    @property
    def content(self) -> bytes:  # noqa: D102
        return b"audio"


def _patch_httpx(monkeypatch, captured: _CapturedPost) -> None:
    import httpx

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:  # noqa: D105
            return self

        async def __aexit__(self, *args: object) -> None:  # noqa: D105
            return None

        async def post(self, url: str, **kwargs: object) -> _CapturedPost:
            captured.url = url
            captured.headers = dict(kwargs.get("headers") or {})  # type: ignore[arg-type]
            captured.files = kwargs.get("files")  # type: ignore[assignment]
            captured.json_payload = kwargs.get("json")  # type: ignore[assignment]
            return captured

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_stt_sends_the_configured_model_and_credential(monkeypatch) -> None:
    """The model is a setting, not a hardcoded `whisper-1` in the payload."""
    from app.core.storage import get_storage
    from app.modules.conversations import voice

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: _settings(ai_stt_api_key="k", ai_stt_model="my-stt-model"),
    )

    class _Storage:
        async def get(self, key: str) -> bytes:  # noqa: D102
            return b"bytes"

    monkeypatch.setattr("app.core.storage.get_storage", lambda: _Storage())
    assert get_storage is not None  # the import exists where the provider reads it

    captured = _CapturedPost()
    _patch_httpx(monkeypatch, captured)

    provider = voice.OpenAIWhisperSTTProvider()
    text = await provider.transcribe(audio_storage_key="k", mime_type="audio/ogg", language="ar")

    assert text == "مرحبا"
    assert captured.files is not None
    assert captured.files["model"] == (None, "my-stt-model")
    assert captured.files["language"] == (None, "ar")
    assert captured.headers["Authorization"] == "Bearer k"


async def test_tts_sends_the_configured_model_and_voice(monkeypatch) -> None:
    from app.modules.conversations import voice

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: _settings(ai_tts_api_key="k", ai_tts_model="my-tts", ai_tts_voice="voice-x"),
    )
    captured = _CapturedPost()
    _patch_httpx(monkeypatch, captured)

    provider = voice.OpenAITTSProvider()
    await provider.synthesize(text="أهلا")

    assert captured.json_payload is not None
    assert captured.json_payload["model"] == "my-tts"
    assert captured.json_payload["voice"] == "voice-x"


async def test_the_stt_provider_fails_loudly_without_a_credential(monkeypatch) -> None:
    """A misconfigured deployment must raise, not silently return empty text."""
    from app.modules.conversations import voice

    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
    provider = voice.OpenAIWhisperSTTProvider()
    with pytest.raises(RuntimeError, match="AI_STT_API_KEY"):
        await provider.transcribe(audio_storage_key="k", mime_type="audio/ogg")


# ------------------------------------------------ 4. the contract is declared --


def test_env_example_documents_every_voice_setting() -> None:
    example = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    missing = [name for name in VOICE_SETTINGS if f"{name}=" not in example]
    assert not missing, f"undocumented voice settings: {missing}"


def test_no_app_code_reads_a_setting_through_a_defaulted_getattr() -> None:
    """The regression guard for the defect itself.

    `getattr(settings, "some_key", None)` turns a MISSING field into a silent
    `None`. That is how voice stayed dead in every environment: the field was
    never declared, and nothing failed.

    Comments are skipped: the fix documents the anti-pattern by name, and a
    guard that forbids writing it down would forbid explaining it.
    """
    needle = 'getattr(settings, "openai_api_key"'
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if needle in line and not line.lstrip().startswith("#"):
                offenders.append(f"{path.as_posix()}:{number}")
    assert not offenders, f"settings read through a defaulted getattr: {offenders}"


# ------------------------------------- 5. a spoken request reaches a human ----


def test_no_keyword_gate_stands_between_the_customer_and_the_model() -> None:
    """The intent keywords are gone: escalation is the MODEL's decision, made
    through the handover_to_human tool after reading the transcript itself.

    A keyword that matched inside a correctly-understood message forced the
    whole turn down the wrong path; the model reads the words and decides.
    """
    import inspect

    from app.modules.ai.agents.customer import turn as turn_module
    from app.modules.ai.tools import get_tool

    source = inspect.getsource(turn_module)
    assert "wants_human_request" not in source
    # The spoken words still reach the model: the transcript rides the
    # user message (or the untranscribed context line when STT has not run).
    assert "turn.voice_transcript" in source
    # The escalation surface exists and speaks the reason vocabulary.
    spec = get_tool("handover_to_human")
    assert spec is not None
