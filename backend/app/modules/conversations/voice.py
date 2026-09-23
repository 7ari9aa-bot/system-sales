"""Spec §35-36 — Voice architecture: STT (Speech-to-Text) + TTS (Text-to-Speech).

Voice messages are a first-class input channel: a customer sends a voice
note on WhatsApp, and the system must:

1. Transcribe it (STT) — so the AI agent can reason about the content
   without a human listening to every voice note.
2. Optionally synthesize a spoken reply (TTS) — so the AI agent can reply
   with a voice note instead of text, which is the natural modality for
   a customer who sent voice.

This module provides the VoiceService with:
- `transcribe()`: send an audio attachment to a STT provider, store the
  transcript text on the Attachment row, and return it.
- `synthesize()`: send text to a TTS provider, store the resulting audio,
  and return a storage key that can be sent as a media message.

Design rules (§36):
- STT is ALWAYS behind the AI budget gate — transcription costs money.
- The transcript is stored on the Attachment row (transcription_status +
  transcript_text), not as a separate message — it is metadata on the voice
  message, not a message itself.
- TTS output is an Attachment on the OUTBOUND message, linked to the text
  message that generated it.
- A provider failure is best-effort: the voice note is still delivered as
  audio; only the transcript is missing. This mirrors the media pipeline's
  "media is a bonus" rule.

The STT/TTS provider is pluggable. The default implementation uses the AI
gateway's chat() with a whisper-like model alias; a future task would plug
in a dedicated STT/TTS provider (OpenAI Whisper, Google Speech-to-Text).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.conversations.models import Attachment

logger = logging.getLogger(__name__)

# A voice note with no reported duration is estimated at a minute.
_STT_FALLBACK_SECONDS = 60


class STTProvider(Protocol):
    """Speech-to-Text provider port."""

    async def transcribe(
        self,
        *,
        audio_storage_key: str,
        mime_type: str,
        language: str | None = None,
    ) -> str:
        """Return the transcript text for the given audio."""
        ...


class TTSProvider(Protocol):
    """Text-to-Speech provider port."""

    async def synthesize(
        self,
        *,
        text: str,
        voice: str | None = None,
        language: str | None = None,
    ) -> tuple[bytes, str]:
        """Return (audio_bytes, mime_type) for the given text."""
        ...


@dataclass(slots=True, frozen=True)
class TranscriptResult:
    """The result of a transcription."""

    text: str
    language: str | None
    duration_seconds: float | None = None


@dataclass(slots=True, frozen=True)
class SynthesisResult:
    """The result of a TTS synthesis."""

    audio_bytes: bytes
    mime_type: str
    storage_key: str | None = None  # set by the caller after storing


class OpenAIWhisperSTTProvider:
    """§35: STT provider using OpenAI's Whisper API.

    Requires OPENAI_API_KEY in settings. If the key is absent, the provider
    raises on first call — VoiceService catches it and marks the attachment
    as failed, preserving the "best-effort" rule.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"

    async def transcribe(
        self,
        *,
        audio_storage_key: str,
        mime_type: str,
        language: str | None = None,
    ) -> str:
        import httpx

        from app.core.config import get_settings

        settings = get_settings()
        key = self._api_key or getattr(settings, "openai_api_key", None)
        if not key:
            raise RuntimeError("OPENAI_API_KEY not configured for STT")

        # Fetch the audio from storage
        from app.core.storage import get_storage

        storage = get_storage()
        audio_bytes = await storage.get(audio_storage_key)

        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {
                "file": ("audio", audio_bytes, mime_type or "audio/mpeg"),
                "model": (None, "whisper-1"),
            }
            if language:
                files["language"] = (None, language)
            resp = await client.post(
                f"{self._base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files=files,
            )
            resp.raise_for_status()
            return resp.json().get("text", "")


class OpenAITTSProvider:
    """§36: TTS provider using OpenAI's TTS API.

    Requires OPENAI_API_KEY in settings. Returns (audio_bytes, mime_type).
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"

    async def synthesize(
        self,
        *,
        text: str,
        voice: str | None = None,
        language: str | None = None,
    ) -> tuple[bytes, str]:
        import httpx

        from app.core.config import get_settings

        settings = get_settings()
        key = self._api_key or getattr(settings, "openai_api_key", None)
        if not key:
            raise RuntimeError("OPENAI_API_KEY not configured for TTS")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/audio/speech",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "tts-1",
                    "input": text,
                    "voice": voice or "alloy",
                },
            )
            resp.raise_for_status()
            return resp.content, "audio/mpeg"


def get_default_stt_provider() -> STTProvider | None:
    """§35: return the default STT provider, or None if not configured."""
    from app.core.config import get_settings

    settings = get_settings()
    if getattr(settings, "openai_api_key", None):
        return OpenAIWhisperSTTProvider(api_key=settings.openai_api_key)
    return None


def get_default_tts_provider() -> TTSProvider | None:
    """§36: return the default TTS provider, or None if not configured."""
    from app.core.config import get_settings

    settings = get_settings()
    if getattr(settings, "openai_api_key", None):
        return OpenAITTSProvider(api_key=settings.openai_api_key)
    return None


class VoiceService:
    """§35-36: voice transcription and synthesis."""

    # Default language for STT/TTS — ar (Arabic) is the deployment default.
    # A per-tenant override would be a future task.
    DEFAULT_LANGUAGE = "ar"

    @staticmethod
    async def transcribe(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        attachment_id: uuid.UUID,
        stt_provider: STTProvider | None = None,
        language: str | None = None,
    ) -> TranscriptResult:
        """§35: transcribe an audio attachment.

        Updates the Attachment's transcription_status and transcript fields.
        Idempotent: if already transcribed, returns the existing transcript.
        """
        attachment = (
            await session.execute(
                select(Attachment).where(
                    Attachment.tenant_id == tenant_id,
                    Attachment.id == attachment_id,
                )
            )
        ).scalar_one_or_none()
        if attachment is None:
            raise NotFoundError("attachment not found")

        # Idempotent: already transcribed
        if attachment.transcription_status == "completed":
            return TranscriptResult(
                text=attachment.transcript_text or "",
                language=attachment.language,
            )

        if attachment.transcription_status == "pending":
            # Another worker is already transcribing — don't race it
            return TranscriptResult(text="", language=attachment.language)

        # Check the attachment is audio
        mime = (attachment.mime_type or "").lower()
        if not mime.startswith("audio/"):
            raise ValidationError(
                f"attachment is not audio (mime={mime})",
                details={"mime_type": mime},
            )

        if attachment.storage_key is None:
            raise ValidationError(
                "attachment has no durable storage key — cannot transcribe"
            )

        # Mark as in-progress
        attachment.transcription_status = "pending"
        await session.flush()

        try:
            if stt_provider is None:
                # §35: try the default provider (OpenAI Whisper) before giving up
                stt_provider = get_default_stt_provider()

            if stt_provider is None:
                # No provider configured — mark as failed, don't crash
                attachment.transcription_status = "failed"
                await session.flush()
                logger.warning(
                    "voice.stt_no_provider tenant=%s attachment=%s",
                    tenant_id,
                    attachment_id,
                )
                return TranscriptResult(text="", language=None)

            text = await stt_provider.transcribe(
                audio_storage_key=attachment.storage_key,
                mime_type=mime,
                language=language or VoiceService.DEFAULT_LANGUAGE,
            )

            attachment.transcription_status = "completed"
            attachment.language = language or VoiceService.DEFAULT_LANGUAGE
            attachment.transcript_text = text
            await session.flush()

            return TranscriptResult(
                text=text,
                language=attachment.language,
            )
        except Exception as exc:
            attachment.transcription_status = "failed"
            await session.flush()
            logger.exception(
                "voice.stt_failed tenant=%s attachment=%s error=%s",
                tenant_id,
                attachment_id,
                type(exc).__name__,
            )
            return TranscriptResult(text="", language=None)

    @staticmethod
    async def synthesize(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        text: str,
        tts_provider: TTSProvider | None = None,
        voice: str | None = None,
        language: str | None = None,
    ) -> SynthesisResult | None:
        """§36: synthesize speech from text.

        Returns the audio bytes + mime type. The caller is responsible for
        storing the bytes and sending them as a media message. Returns None
        if no TTS provider is configured (the text message is sent as-is).
        """
        if not text or not text.strip():
            raise ValidationError("text must not be empty")

        if tts_provider is None:
            logger.warning(
                "voice.tts_no_provider tenant=%s — text will be sent as text only",
                tenant_id,
            )
            return None

        try:
            audio_bytes, mime_type = await tts_provider.synthesize(
                text=text,
                voice=voice,
                language=language or VoiceService.DEFAULT_LANGUAGE,
            )
            return SynthesisResult(
                audio_bytes=audio_bytes,
                mime_type=mime_type,
                storage_key=None,  # caller stores and sets this
            )
        except Exception as exc:
            logger.exception(
                "voice.tts_failed tenant=%s error=%s",
                tenant_id,
                type(exc).__name__,
            )
            return None


def stt_cost_estimate(attachment: Attachment) -> Decimal:
    """§36: what this transcription is expected to cost, for the budget gate.

    Whisper is billed per minute of audio, so the attachment's own duration is
    the estimate. A missing duration is charged as a full minute — over-estimating
    holds budget, which is the safe direction for a cap.
    """
    from app.core.config import get_settings

    rate = Decimal(str(get_settings().ai_stt_cost_per_minute))
    seconds = attachment.duration or _STT_FALLBACK_SECONDS
    return (rate * Decimal(seconds) / Decimal(60)).quantize(Decimal("0.0001"))


__all__ = [
    "STTProvider",
    "TTSProvider",
    "TranscriptResult",
    "SynthesisResult",
    "VoiceService",
    "stt_cost_estimate",
]
