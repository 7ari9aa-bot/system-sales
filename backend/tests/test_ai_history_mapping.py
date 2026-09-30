"""A3 — how a `messages` row becomes a turn the provider sees.

``_conversation_context`` maps a row to a role from ONE column:
``role = "assistant" if direction == "outbound" else "user"``. That is wrong in
four ways the tests below pin:

* an outbound row whose send ``failed`` (or whose result is ``unknown``) never
  reached the customer, and replaying it teaches the model that it already said
  something it did not;
* a ``system`` row is a platform notice — authored by neither the customer nor
  the assistant — and as an assistant turn the model adopts it as its own words;
* the message being answered is itself the newest history row, so the prompt
  carried it twice;
* a body-less non-audio message (image, file, video, location) was dropped in
  silence, so a customer who sent a picture looked like they had said nothing.

Audio is the exception that already worked (§35), and it stays working.

The mapper is pure, so every case here runs without a database by handing it
in-memory ``Message`` rows. The last test is DB-backed and skips locally: CI is
the only venue where "the fetch and the mapping agree" means anything.
"""

from __future__ import annotations

import uuid

from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.models import Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a3")
CONVERSATION_ID = uuid.UUID("00000000-0000-0000-0000-0000000003a3")


def _msg(**overrides) -> Message:
    # Un-flushed rows get no column defaults, so state every column the mapper
    # reads; a typo here shows up as a missing turn, not a silent pass.
    fields: dict = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        direction="inbound",
        sender_type="customer",
        body="hello",
        status="received",
        content_type="text",
        media_url=None,
        media_type=None,
    )
    fields.update(overrides)
    return Message(**fields)


def _turns(rows, *, voice=None, current_message=None):
    return AgentRunner._provider_turns(rows, voice=voice or {}, current_message=current_message)


def _outbound(*, status: str = "delivered", **overrides) -> Message:
    return _msg(direction="outbound", sender_type="ai", status=status, **overrides)


# ------------------------------------------------ delivered vs not --------


def test_an_outbound_message_the_customer_never_received_is_not_a_turn() -> None:
    rows = [_outbound(body="Your order shipped today.", status="failed")]

    assert _turns(rows) == [], (
        "a send that failed was replayed to the model as something it had "
        "already told the customer"
    )


def test_an_outbound_send_whose_result_is_lost_is_not_a_turn() -> None:
    rows = [_outbound(body="Your order shipped today.", status="unknown")]

    assert _turns(rows) == []


def test_a_delivered_reply_is_still_an_assistant_turn() -> None:
    rows = [_outbound(body="Your order ships tomorrow.", status="delivered")]

    assert _turns(rows) == [{"role": "assistant", "content": "Your order ships tomorrow."}]


def test_a_staff_reply_from_within_the_window_is_an_assistant_turn() -> None:
    rows = [
        _msg(
            direction="outbound",
            sender_type="agent",
            status="sent",
            body="I can help with that.",
        )
    ]

    assert _turns(rows) == [{"role": "assistant", "content": "I can help with that."}]


def test_a_reply_still_in_flight_is_left_alone() -> None:
    """Only a send that ended unresolved or badly is refused; a reply that is
    still queued may well land, and dropping it would make the model answer the
    same question twice."""
    rows = [_outbound(body="Draft answer.", status="queued")]

    assert _turns(rows) == [{"role": "assistant", "content": "Draft answer."}]


# ------------------------------------------------------ system notices ----


def test_a_platform_notice_is_not_put_in_the_assistants_mouth() -> None:
    rows = [
        _msg(
            direction="outbound",
            sender_type="system",
            status="delivered",
            body="Marketing blast: 20% off this week only.",
        )
    ]

    turns = _turns(rows)
    assert [t for t in turns if t["role"] == "assistant"] == [], (
        "a system notice was replayed as the assistant's own utterance"
    )
    assert turns == []


def test_a_customer_turn_is_unaffected_by_its_neighbour_being_a_notice() -> None:
    rows = [
        _msg(
            direction="outbound",
            sender_type="system",
            status="delivered",
            body="Conversation assigned to a human.",
        ),
        _msg(body="Do you have the blue one in size M?"),
    ]

    assert _turns(rows) == [
        {"role": "user", "content": "Do you have the blue one in size M?"}
    ]


# ------------------------------------------------ the duplicated current --


def test_the_message_being_answered_is_not_also_history() -> None:
    """The runner appends ``user_message`` itself; the row it came from is the
    newest history row, so the prompt carried the same text twice."""
    rows = [
        _msg(body="how much is the blue widget?", status="received"),
    ]

    assert _turns(rows, current_message="how much is the blue widget?") == []


def test_an_older_repetition_of_the_current_words_survives() -> None:
    rows = [
        _msg(body="still waiting"),
        _outbound(body="Sorry for the delay."),
        _msg(body="still waiting"),
    ]

    turns = _turns(rows, current_message="still waiting")
    assert turns == [
        {"role": "user", "content": "still waiting"},
        {"role": "assistant", "content": "Sorry for the delay."},
    ]


def test_history_without_the_current_message_is_returned_unchanged() -> None:
    rows = [_msg(body="hello"), _outbound(body="Hi!"), _msg(body="price?")]

    assert _turns(rows, current_message="price?") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi!"},
    ]


# ------------------------------------------------------ media-only rows ----


def test_a_picture_the_customer_sent_is_visible_to_the_model() -> None:
    rows = [_msg(body=None, content_type="image", media_url="https://x.test/a.jpg")]

    turns = _turns(rows)
    assert len(turns) == 1
    assert turns[0]["role"] == "user"
    assert "image" in turns[0]["content"].lower(), (
        "a media-only message has to read as media, not as silence"
    )


def test_a_location_or_document_says_what_it_is() -> None:
    for content_type in ("location", "file", "video"):
        turns = _turns([_msg(body=None, content_type=content_type)])
        assert len(turns) == 1, content_type
        assert content_type in turns[0]["content"].lower()


def test_a_transcribed_voice_note_still_reads_as_the_customer_speaking() -> None:
    spoken = _msg(body=None, content_type="voice")
    voice = {spoken.id: ("completed", "اريد السعر")}

    turns = _turns([spoken], voice=voice)

    assert len(turns) == 1
    assert turns[0]["role"] == "user"
    assert "اريد السعر" in turns[0]["content"]


def test_an_unintelligible_empty_row_stays_out_of_the_prompt() -> None:
    """No body, no media, no content kind — nothing to tell the model."""
    assert _turns([_msg(body=None)]) == []


# ------------------------------------------------- the fetched pairing -----


async def test_the_fetched_history_deduplicates_the_current_message(
    db, tenant_ctx
) -> None:
    """DB-backed (CI only): the fetch and the mapping have to agree that the
    turn being answered is not also replayed above it."""
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_ctx.tenant_id, "webchat", f"wc-{uuid.uuid4().hex[:10]}", name="A3"
    )
    conversation = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )
    await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="how much is the blue widget?",
    )

    history, _image_key = await AgentRunner._conversation_context(
        db,
        tenant_ctx.tenant_id,
        conversation.id,
        current_message="how much is the blue widget?",
    )

    assert history == []
