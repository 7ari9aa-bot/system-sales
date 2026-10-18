"""§33-36 — inbound voice notes reach the agent, budget-gated.

`conversations/voice.py` implemented STT/TTS but nothing ever called it: every
real WhatsApp voice note landed as an Attachment with `transcription_status`
NULL, no transcript anywhere queryable, and `AgentRunner._conversation_context`
skips messages with an empty body — so the agent saw *nothing at all* for a
customer who spoke.

These tests pin the wiring, in the order the pipeline needs it:

    ingest marks audio pending → worker transcribes (budget gate, cost
    recorded, failure contained) → transcript lands on the Attachment →
    the agent's context shows the transcript instead of silence.

DB-backed cases skip without Postgres; CI runs them against the real schema,
which is the only place "the transcript survived the migration" means anything.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.ai.models import AIUsage, BudgetPolicy
from app.modules.ai.runtime import AgentRunner, _customer_user_content, _omni_audio_content_part
from app.modules.conversations.media import (
    FetchedMedia,
    MediaService,
    StoredMedia,
)
from app.modules.conversations.models import Attachment, Message
from app.modules.conversations.service import ConversationService
from app.modules.conversations.voice import omni_audio_format
from app.modules.customers.service import CustomerService
from app.workers.message_worker import transcribe_inbound_voice

VOICE_URL = "https://cdn.example.test/voice1.ogg"
VOICE_BYTES = b"OggS\x02\x00\x00\x00fake-opus-frame"
TRANSCRIPT = "عايز اعرف سعر اللون الأزرق"


@pytest.mark.parametrize(
    ("mime", "expected"),
    [
        ("audio/ogg", "ogg"),
        ("audio/opus", "ogg"),
        ("application/ogg", "ogg"),
        ("audio/wav", "wav"),
        ("audio/mpeg", "mp3"),
        ("audio/x-ms-wma", None),
        ("application/octet-stream", None),
    ],
)
def test_omni_audio_format_is_allow_listed(mime: str, expected: str | None) -> None:
    assert omni_audio_format(mime) == expected


def test_omni_audio_content_part_carries_encoded_bytes_and_format() -> None:
    part = _omni_audio_content_part("audio/ogg", b"OggSvoice-bytes")
    assert part is not None
    assert part["type"] == "input_audio"
    assert part["input_audio"]["format"] == "ogg"
    assert part["input_audio"]["data"].startswith("data:audio/ogg;base64,")


def test_customer_user_content_keeps_text_image_and_audio_together() -> None:
    audio = _omni_audio_content_part("audio/ogg", b"OggSvoice-bytes")
    parts = _customer_user_content(
        "ممكن تساعدني؟", image_url="https://storage.test/photo.jpg", audio_part=audio
    )
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "ممكن تساعدني؟"}
    assert parts[1]["type"] == "image_url"
    assert parts[2]["type"] == "input_audio"


class _VoiceStorage:
    """The S3 port for one audio object."""

    def __init__(self, *, content_type: str = "audio/ogg") -> None:
        self.content_type = content_type

    async def fetch(self, url: str, *, max_bytes=None) -> FetchedMedia:
        return FetchedMedia(
            data=VOICE_BYTES,
            content_type=self.content_type,
            checksum=hashlib.sha256(VOICE_BYTES).hexdigest(),
        )

    async def store(
        self, media, *, prefix: str = "media", original_url: str | None = None
    ) -> StoredMedia:
        return StoredMedia(
            url="https://bucket.test/media/voice1.ogg",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=True,
            storage_key="media/voice1.ogg",
            checksum=media.checksum,
        )


class _FakeSTT:
    """An STT provider that records being asked, and can fail on purpose."""

    def __init__(self, *, text: str = TRANSCRIPT, error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    async def transcribe(
        self, *, audio_storage_key: str, mime_type: str, language: str | None = None
    ) -> str:
        self.calls.append({"key": audio_storage_key, "mime": mime_type, "language": language})
        if self.error is not None:
            raise self.error
        return self.text


async def _conversation(db, tenant_id) -> object:
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name="Voice Tester"
    )
    return await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )


async def _voice_note(db, tenant_id, conversation, *, body: str | None = None) -> Message:
    return await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body=body,
        media_url=VOICE_URL,
        media_type="audio",
        channel_message_id=f"wamid-{uuid.uuid4().hex[:12]}",
        media_storage=_VoiceStorage(),
    )


async def _attachment_of(db, tenant_id, message_id) -> Attachment:
    return (await MediaService.list_for_message(db, tenant_id, message_id))[0]


async def test_only_scanned_audio_is_eligible_for_direct_omni(db, tenant_ctx, monkeypatch):
    import app.modules.ai.runtime as runtime_module

    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    attachment = await _attachment_of(db, tenant_id, message.id)
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: SimpleNamespace(ai_voice_audio_input=True),
    )

    attachment.scan_status = "pending"
    await db.flush()
    _turns, _image, audio = await AgentRunner._conversation_context(db, tenant_id, conversation.id)
    assert audio is None, "unscanned audio must not egress to Omni"

    attachment.scan_status = "scanned"
    await db.flush()
    _turns, _image, audio = await AgentRunner._conversation_context(db, tenant_id, conversation.id)
    assert audio == ("audio/ogg", "media/voice1.ogg")


# ------------------------------------------------- §33-34: ingest queues ----


async def test_inbound_audio_is_queued_for_transcription(db, tenant_ctx) -> None:
    """A durable audio object is a transcription job — nothing else sets it off.

    Before this, `transcription_status` stayed NULL on every real voice note:
    the only writer was `VoiceService`, which had no caller.
    """
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)

    message = await _voice_note(db, tenant_id, conversation)
    attachment = await _attachment_of(db, tenant_id, message.id)

    assert attachment.mime_type == "audio/ogg"
    assert attachment.scan_status == "pending"  # no scanner: direct Omni egress stays closed
    assert attachment.transcription_status == "pending"


async def test_transcribe_inbound_voice_is_a_noop_without_pending_audio(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="نص عادي",
        channel_message_id=f"wamid-{uuid.uuid4().hex[:12]}",
    )
    stt = _FakeSTT()

    transcript = await transcribe_inbound_voice(
        db, tenant_id, message_id=message.id, stt_provider=stt
    )
    assert transcript is None
    assert stt.calls == []


async def test_transcribe_inbound_voice_transcribes_and_persists_the_transcript(
    db, tenant_ctx
) -> None:
    """The transcript has to survive on the row: `transcript_id` is a pointer,
    not the text, and an agent turn is rebuilt from the attachment later."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    stt = _FakeSTT()

    text = await transcribe_inbound_voice(db, tenant_id, message_id=message.id, stt_provider=stt)

    assert text == TRANSCRIPT
    assert stt.calls == [{"key": "media/voice1.ogg", "mime": "audio/ogg", "language": "ar"}]
    message_id = message.id
    db.expire_all()
    attachment = await _attachment_of(db, tenant_id, message_id)
    assert attachment.transcription_status == "completed"
    assert attachment.transcript_text == TRANSCRIPT
    assert attachment.language == "ar"


async def test_provider_failure_leaves_the_voice_note_delivered_and_marked_failed(
    db, tenant_ctx
) -> None:
    """§36 best-effort: a dead STT provider must not lose the customer's note
    and must not raise into the worker (that would retry and dead-letter a
    perfectly well-ingested message)."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    stt = _FakeSTT(error=RuntimeError("whisper unreachable"))

    transcript = await transcribe_inbound_voice(
        db, tenant_id, message_id=message.id, stt_provider=stt
    )
    assert transcript is None
    attachment = await _attachment_of(db, tenant_id, message.id)
    assert attachment.transcription_status == "failed"


async def test_already_transcribed_message_does_not_pay_for_it_twice(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    first = _FakeSTT()
    await transcribe_inbound_voice(db, tenant_id, message_id=message.id, stt_provider=first)

    second = _FakeSTT(text="re-transcribed")
    second_run = await transcribe_inbound_voice(
        db, tenant_id, message_id=message.id, stt_provider=second
    )
    assert second_run is None
    assert second.calls == []


# ------------------------------------------------- §36: the budget gate -----


async def _exhaust_budget(db, tenant_id, *, cap: str = "1.00", spent: str = "5.00") -> None:
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            period="monthly",
            hard_cap=Decimal(cap),
            on_exceed="block",
        )
    )
    db.add(
        AIUsage(
            tenant_id=tenant_id,
            period_date=datetime.now(UTC).date(),
            cost=Decimal(spent),
            tokens_in=0,
            tokens_out=0,
            model_calls=1,
        )
    )
    await db.flush()


async def test_transcription_is_blocked_when_the_budget_is_exhausted(db, tenant_ctx) -> None:
    """§36: STT is ALWAYS behind the AI budget gate — transcription costs money.

    The gate must be consulted BEFORE the provider call, so an over-budget
    tenant never pays for a transcript it cannot use.
    """
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    await _exhaust_budget(db, tenant_id)
    stt = _FakeSTT()

    transcript = await transcribe_inbound_voice(
        db, tenant_id, message_id=message.id, stt_provider=stt
    )
    assert transcript is None
    assert stt.calls == []
    attachment = await _attachment_of(db, tenant_id, message.id)
    assert attachment.transcription_status == "failed"


async def test_successful_transcription_is_recorded_as_spend(db, tenant_ctx) -> None:
    """A cost that is paid but never booked is invisible to §42's cap — the
    next caller would reserve against a spend figure that excludes it."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)

    text = await transcribe_inbound_voice(
        db, tenant_id, message_id=message.id, stt_provider=_FakeSTT()
    )
    assert text == TRANSCRIPT

    spend = (
        (
            await db.execute(
                select(AIUsage.cost).where(
                    AIUsage.tenant_id == tenant_id,
                    AIUsage.period_date >= datetime.now(UTC).date().replace(day=1),
                )
            )
        )
        .scalars()
        .all()
    )
    assert sum(Decimal(c or 0) for c in spend) > Decimal("0")


# ------------------------------------------ §35: the agent sees it ---------


async def _voice_transcript_in_history(db, tenant_ctx, *, transcript: str | None) -> list[dict]:
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    attachment = await _attachment_of(db, tenant_id, message.id)
    if transcript is None:
        attachment.transcription_status = "pending"
    else:
        attachment.transcription_status = "completed"
        attachment.transcript_text = transcript
    await db.flush()
    turns, _image_key, _audio = await AgentRunner._conversation_context(
        db, tenant_id, conversation.id
    )
    return turns


async def test_voice_transcript_becomes_the_customer_turn(db, tenant_ctx) -> None:
    """A voice note with no body used to be `continue`d out of the context —
    the agent answered a question it never received."""
    history = await _voice_transcript_in_history(db, tenant_ctx, transcript=TRANSCRIPT)

    turns = [m for m in history if m["role"] == "user"]
    assert len(turns) == 1
    assert TRANSCRIPT in turns[0]["content"]
    assert "voice" in turns[0]["content"].lower()


async def test_untranscribed_voice_note_is_visible_not_silent(db, tenant_ctx) -> None:
    """Transcript not ready yet (or it failed): the agent must still know the
    customer sent audio, instead of treating an empty conversation as no ask."""
    history = await _voice_transcript_in_history(db, tenant_ctx, transcript=None)

    turns = [m for m in history if m["role"] == "user"]
    assert len(turns) == 1
    assert "transcript" in turns[0]["content"].lower()


async def test_text_message_still_becomes_its_own_body(db, tenant_ctx) -> None:
    """Regression guard for the context change: a plain message must not pick
    up any voice framing."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="سعر اللون الأزرق؟",
        channel_message_id=f"wamid-{uuid.uuid4().hex[:12]}",
    )

    history, _image_key, _audio = await AgentRunner._conversation_context(
        db, tenant_id, conversation.id
    )
    assert history[-1] == {"role": "user", "content": "سعر اللون الأزرق؟"}


# ------------------------------------------------- the worker seam ----------


@pytest.mark.parametrize("direct_omni", [False, True], ids=["stt-legacy", "direct-omni"])
async def test_message_worker_uses_one_voice_understanding_path(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch, direct_omni
) -> None:
    """STT and direct Omni are mutually exclusive: direct mode never calls
    Whisper, while the default/legacy mode preserves transcript-before-reply."""
    import app.core.config as config
    import app.workers.message_worker as mw
    from app.core.events.schemas import EventEnvelope
    from app.modules.ai import hooks as ai_hooks

    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    order: list[str] = []

    async def fake_transcribe(session, tid, *, message_id, **kwargs):
        order.append("transcribe")
        return TRANSCRIPT

    async def fake_auto_reply(session, tid, conversation_id, *, inbound_message_id=None):
        order.append("reply")

    monkeypatch.setattr(mw, "SessionLocal", app_sessions_on_test_connection)
    monkeypatch.setattr(
        config, "get_settings", lambda: SimpleNamespace(ai_voice_audio_input=direct_omni)
    )
    monkeypatch.setattr(mw, "transcribe_inbound_voice", fake_transcribe)
    monkeypatch.setattr(ai_hooks, "maybe_auto_reply", fake_auto_reply)

    envelope = EventEnvelope(
        type="message.received",
        tenant_id=tenant_id,
        aggregate_type="message",
        aggregate_id=message.id,
        payload={
            "conversation_id": str(conversation.id),
            "channel": "whatsapp",
            "media_type": "audio",
        },
    )
    worker = mw.MessageWorker.__new__(mw.MessageWorker)  # bus unused
    worker.name = "test"
    await worker._on_received(envelope)

    assert order == (["reply"] if direct_omni else ["transcribe", "reply"])


# ------------------------------------------------ §8b: direct-Omni context ---


def test_runtime_module_resolves_omni_audio_format() -> None:
    """DB-free guard for the 405e924 regression: the refactor deleted the
    `omni_audio_format` import from runtime.py while its two call sites
    remained — every voice turn on the direct path raised NameError and the
    ruff F821 that should have caught it was buried under a repo-wide red
    lint gate. The symbol must resolve in the module that calls it."""
    import app.modules.ai.runtime as runtime_module

    assert callable(runtime_module.omni_audio_format)
    assert runtime_module.omni_audio_format("audio/ogg") == "ogg"


def test_voice_context_line_yields_when_audio_rides() -> None:
    """The 'please type it' line contradicts the audio bytes the model is
    about to hear — it fires only when the audio will NOT reach the model."""
    from app.modules.ai.agents.customer.intake import InboundTurn
    from app.modules.ai.agents.customer.turn import _context_lines

    turn = InboundTurn(text=None, has_voice=True, voice_transcript=None)
    # Audio rides: no contradictory line — the model hears the customer.
    assert _context_lines(turn, None, None, None, [], 0, 0, audio_rides=True) is None
    # Audio does not ride: the ask-to-type line stays.
    surfaced = _context_lines(turn, None, None, None, [], 0, 0, audio_rides=False)
    assert surfaced is not None
    assert "صوتية" in surfaced


@pytest.mark.parametrize("direct_omni", [True, False])
async def test_hook_tells_the_coordinator_whether_audio_rides(
    db, tenant_ctx, monkeypatch, direct_omni
) -> None:
    """The hook owns the attachment scan statuses and the settings flag, so it
    — not the coordinator — decides whether the voice context line applies."""
    from app.modules.ai import hooks as ai_hooks
    from app.modules.ai.agents.customer.turn import TurnInput, TurnOutcome
    from app.modules.ai.models import Agent

    tenant_id = tenant_ctx.tenant_id
    db.add(Agent(tenant_id=tenant_id, name="Customer", kind="customer", model="fast"))
    await db.flush()
    conversation = await _conversation(db, tenant_id)
    message = await _voice_note(db, tenant_id, conversation)
    attachment = await _attachment_of(db, tenant_id, message.id)
    attachment.scan_status = "scanned"
    await db.flush()

    captured: list[TurnInput] = []

    async def fake_turn(session, params, *, runner=None, deadline_seconds=45.0):
        captured.append(params)
        return TurnOutcome(reply="ok", state_version=1)

    monkeypatch.setattr(ai_hooks, "run_customer_turn", fake_turn)
    monkeypatch.setattr(
        ai_hooks, "get_settings", lambda: SimpleNamespace(ai_voice_audio_input=direct_omni)
    )

    await ai_hooks.maybe_auto_reply(db, tenant_id, conversation.id, inbound_message_id=message.id)

    assert len(captured) == 1
    assert captured[0].audio_rides is direct_omni
