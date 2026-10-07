"""Turn intake tests (spec §8/§155) — pure normalization, no database.

Pins the shapes every downstream consumer relies on: photo turns carry
durable keys in order, captions survive as the embed hint, a voice note
without a transcript is a VISIBLE state, and unrecognized media is
acknowledged without being interpreted.
"""

from __future__ import annotations

from app.modules.ai.agents.customer.intake import build_turn


def test_text_only_turn():
    turn = build_turn(body="الكام؟", content_type="text", attachments=[], transcript=None)
    assert turn.text == "الكام؟"
    assert not turn.is_image_turn and not turn.has_voice and not turn.other_media


def test_photo_turn_carries_durable_keys_in_order():
    turn = build_turn(
        body=None,
        content_type="image",
        attachments=[
            ("image/jpeg", "photos/first.png"),
            ("application/pdf", "docs/x.pdf"),
            ("image/png", None),  # captured provider URL, no durable key
            ("image/png", "photos/second.png"),
        ],
    )
    assert turn.is_image_turn
    # Only images WITH durable keys survive, in arrival order; the pdf and
    # the keyless entry are not photos.
    assert turn.image_keys == ["photos/first.png", "photos/second.png"]
    assert turn.other_media  # the pdf was present and acknowledged


def test_photo_with_caption_keeps_both():
    turn = build_turn(
        body="زي ده بس أسود",
        content_type="image",
        attachments=[("image/jpeg", "photos/a.png")],
    )
    assert turn.is_image_turn and turn.text == "زي ده بس أسود"
    assert turn.text_hint() == "زي ده بس أسود"


def test_voice_without_transcript_is_a_visible_state():
    turn = build_turn(body=None, content_type="voice", attachments=[], transcript=None)
    assert turn.has_voice and turn.voice_transcript is None


def test_voice_with_transcript():
    turn = build_turn(
        body=None,
        content_type="voice",
        attachments=[("audio/ogg", None)],
        transcript="عايز تاني واحد  ",
    )
    assert turn.has_voice and turn.voice_transcript == "عايز تاني واحد"


def test_video_and_file_are_other_media():
    for kind in ("video", "file", "location"):
        turn = build_turn(body=None, content_type=kind, attachments=[])
        assert turn.other_media and not turn.is_image_turn


def test_blank_body_is_not_text():
    turn = build_turn(body="   ", content_type="text", attachments=[])
    assert turn.text is None
