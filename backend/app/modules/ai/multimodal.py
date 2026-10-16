"""AI Multimodal content preparation — audio, image, and tool call payload shaping.

Handles OpenAI-compatible payload generation for:
- Qwen Omni direct audio inputs (_omni_audio_content_part)
- Image attachment references (_customer_user_content)
- Assistant tool calls including Gemini 3.x thought signatures (_assistant_tool_call)
"""

from __future__ import annotations

import base64
import json

from app.modules.ai.providers import ToolCallRequest
from app.modules.conversations.voice import omni_audio_format


def _omni_audio_content_part(audio_mime: str, audio_bytes: bytes) -> dict | None:
    """Build a Qwen Omni OpenAI-compatible ``input_audio`` part.

    The format map is deliberately allow-listed: never label an unknown
    container as WAV/OGG. Bytes arrive only after the attachment's scanner
    verdict is ``scanned`` and are read from our own storage.
    """
    audio_format = omni_audio_format(audio_mime)
    if audio_format is None or not audio_bytes:
        return None
    data_url = f"data:{audio_mime};base64,{base64.b64encode(audio_bytes).decode('ascii')}"
    return {"type": "input_audio", "input_audio": {"data": data_url, "format": audio_format}}


def _customer_user_content(
    user_message: str,
    *,
    image_url: str | None = None,
    audio_part: dict | None = None,
) -> str | list[dict]:
    """Build one OpenAI-compatible user content value, preserving both media."""
    if not image_url and not audio_part:
        return user_message
    parts: list[dict] = [{"type": "text", "text": user_message}]
    if image_url:
        parts.append({"type": "image_url", "image_url": {"url": image_url}})
    if audio_part:
        parts.append(audio_part)
    return parts


def _assistant_tool_call(tc: ToolCallRequest) -> dict:
    """OpenAI tool_call entry — with Gemini 3.x thought_signature when present
    (required on the next turn, otherwise the provider 400s)."""
    entry: dict = {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments or {})},
    }
    if tc.thought_signature:
        entry["extra_content"] = {"google": {"thought_signature": tc.thought_signature}}
    return entry
