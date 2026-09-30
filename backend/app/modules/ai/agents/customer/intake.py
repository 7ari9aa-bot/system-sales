"""Turn intake (spec §8) — normalize the customer's raw turn.

Everything downstream needs ONE shape, not six ways of asking "did the
customer send a photo?". This module turns the raw message fields plus the
attachments the runtime already fetched into an ``InboundTurn``. Pure: no
DB, no providers — the runtime owns fetches and passes rows in.

Vocabulary follows the §155 canonical content kinds the messages table
already uses (text | image | voice | video | file | location | contact).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InboundTurn:
    """The customer's turn, normalized."""

    # The customer's words, if any. A photo WITH a caption keeps both — the
    # caption rides the image embed (§12.1) and stays the reply's topic.
    text: str | None = None
    # Durable storage keys of the photos on this turn, in arrival order.
    image_keys: list[str] = field(default_factory=list)
    # A voice note. transcript None + has_voice True is a STATE the caller
    # must surface ("we could not hear them yet"), never silently hide.
    has_voice: bool = False
    voice_transcript: str | None = None
    # file/video/location/contact: present, acknowledged, not interpreted.
    other_media: bool = False

    @property
    def is_image_turn(self) -> bool:
        return bool(self.image_keys)

    def text_hint(self) -> str | None:
        """The words to ride WITH an image embed — the caption itself."""
        return self.text


def build_turn(
    *,
    body: str | None,
    content_type: str | None,
    attachments: list[tuple[str, str | None]],
    transcript: str | None = None,
) -> InboundTurn:
    """Normalize one inbound message.

    ``attachments`` are (mime_type, storage_key) pairs in arrival order;
    entries without a durable storage key are skipped (a provider URL that
    was never captured expires and cannot be re-fetched later anyway).
    """
    text = body.strip() if body and body.strip() else None
    image_keys = [
        key
        for mime, key in attachments
        if key and (mime or "").lower().startswith("image/")
    ]
    kind = (content_type or "").strip().lower()
    has_voice = kind == "voice" or any(
        (mime or "").lower().startswith("audio/") for mime, _ in attachments
    )
    other_media = kind in {"file", "video", "location", "contact"} or any(
        mime
        and not (mime or "").lower().startswith(("image/", "audio/"))
        for mime, _ in attachments
    )
    return InboundTurn(
        text=text,
        image_keys=image_keys,
        has_voice=has_voice,
        voice_transcript=(transcript.strip() or None) if transcript else None,
        other_media=other_media,
    )
