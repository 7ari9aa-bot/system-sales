"""ADR-062 (amended) — the customer-image vision egress gate, on the real paths.

Two doors lead from an inbound photo to an external vision provider, and the
tests below walk both REAL ones — the gate is never re-implemented or mocked:

* the auto-reply hook (``hooks.py``) mints the URL the coordinator's vision
  pass sends to the external embedding-vision provider;
* the runner's media selection (``runtime.py`` ``_conversation_context`` —
  the region the plan called ``_resolve_turn_media``) signs the URL that
  rides the multimodal model part.

Both must admit ONLY ``scan_status="scanned"``. A pending image (no scanner
configured, or a scanner outage), a quarantined one, and a failed one are
refused at both doors — the turn degrades gracefully (the coordinator sees
no image, answers without vision) instead of egressing unscanned bytes.

The first section runs the real hook; the second seeds Attachment rows at
each pipeline state directly, because the VERDICT vocabulary — not the clamd
transport (that is ``test_media_pipeline.py``) — is what these gates read;
the last section proves the ingest-side fail-closed default end to end.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.ai.hooks as hooks_mod
from app.modules.ai.agents.customer import turn as turn_module
from app.modules.ai.agents.customer.turn import TurnInput, TurnOutcome, run_customer_turn
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner, AgentRunResult
from app.modules.conversations import models as conv_models
from app.modules.conversations.media import MediaService
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
from tests.test_customer_turn import FakeRunner
from tests.test_media_pipeline import MEDIA_URL, FakeStorage, _set_scanner

STORAGE_KEY = "media/scanned-photo.png"


# ------------------------------------------------------------- seeding -----


async def _conversation_with_image(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    scan_status: str,
    processing_status: str = "pending",
):
    """A customer + conversation + inbound image message + one Attachment.

    The Attachment is seeded at an explicit pipeline state: the point is what
    each GATE reads, not how media.py reaches that state (the scanner
    integration tests own that side).
    """
    customer = Customer(tenant_id=tenant_id, name=f"Egress Customer {uuid.uuid4().hex[:8]}")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    # A bare image message row (no body, no provider media): add_message
    # refuses such a shape, but the gate-under-test reads the ATTACHMENT, and
    # the hook's fallback picks an inbound image row up by content_type.
    message = conv_models.Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        content_type="image",
        media_type="image",
        status="received",
    )
    db.add(message)
    await db.flush()
    db.add(
        conv_models.Attachment(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            message_id=message.id,
            storage_key=STORAGE_KEY,
            mime_type="image/png",
            scan_status=scan_status,
            processing_status=processing_status,
        )
    )
    await db.flush()
    return conversation


async def _agent(db, tenant_id: uuid.UUID) -> None:
    """The customer-kind agent the hook resolves (kind defaults via the row)."""
    db.add(Agent(tenant_id=tenant_id, name="Customer Agent", model="fast", system_prompt="s"))
    await db.flush()


def _capture_turn(monkeypatch: pytest.MonkeyPatch) -> list[TurnInput]:
    """Replace the turn call INSIDE the hook and record its full input.

    The hook builds `image_urls` itself — capturing TurnInput is exactly the
    observation the gate needs: which URLs were minted for the provider.
    """
    captured: list[TurnInput] = []

    async def fake_turn(session, params: TurnInput, **kwargs) -> TurnOutcome:
        captured.append(params)
        return TurnOutcome(reply="وصلت الصورة")

    monkeypatch.setattr(hooks_mod, "run_customer_turn", fake_turn)
    return captured


def _patch_signed_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic URL minting inside the hook (the real port is unconfigured)."""
    monkeypatch.setattr(
        hooks_mod,
        "get_storage",
        lambda: type(
            "S", (), {"public_url": staticmethod(lambda key: f"https://signed.test/{key}")}
        )(),
    )


# ------------------------------------------------- hook door (hooks.py) ----


async def test_a_pending_image_gets_no_provider_url(db, tenant_ctx, monkeypatch):
    """The unconfigured-scanner default: durable image stays pending → no URL."""
    tenant_id = tenant_ctx.tenant_id
    await _agent(db, tenant_id)
    conversation = await _conversation_with_image(db, tenant_id, scan_status="pending")
    _patch_signed_urls(monkeypatch)
    captured = _capture_turn(monkeypatch)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    assert len(captured) == 1
    # The turn still knows a photo EXISTS (the placeholder body), but no URL
    # was minted — the coordinator can only answer without vision.
    assert captured[0].image_urls == {}
    assert captured[0].body == "[Customer sent an image]"


async def test_a_failed_or_quarantined_image_gets_no_provider_url(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    await _agent(db, tenant_id)
    captured = _capture_turn(monkeypatch)
    _patch_signed_urls(monkeypatch)

    failed = await _conversation_with_image(
        db, tenant_id, scan_status="failed", processing_status="failed"
    )
    await maybe_auto_reply(db, tenant_id, failed.id)
    quarantined = await _conversation_with_image(db, tenant_id, scan_status="quarantined")
    await maybe_auto_reply(db, tenant_id, quarantined.id)

    assert [params.image_urls for params in captured] == [{}, {}]


async def test_a_scanned_image_gets_its_url(db, tenant_ctx, monkeypatch):
    """The only admissible state: scanned (+ processed — and scanned alone)."""
    tenant_id = tenant_ctx.tenant_id
    await _agent(db, tenant_id)
    captured = _capture_turn(monkeypatch)
    _patch_signed_urls(monkeypatch)

    processed = await _conversation_with_image(
        db, tenant_id, scan_status="scanned", processing_status="processed"
    )
    await maybe_auto_reply(db, tenant_id, processed.id)
    assert captured[-1].image_urls == {STORAGE_KEY: f"https://signed.test/{STORAGE_KEY}"}

    # The REAL production shape: no transcoder exists, so a scanned row sits
    # at processing "pending". ADR-062 (amended) records that gap and keeps
    # the gate scan-only — this must stay admitted.
    pending_processing = await _conversation_with_image(
        db, tenant_id, scan_status="scanned", processing_status="pending"
    )
    await maybe_auto_reply(db, tenant_id, pending_processing.id)
    assert captured[-1].image_urls == {STORAGE_KEY: f"https://signed.test/{STORAGE_KEY}"}


# ------------------------------------------------ runtime door (runtime.py) --


async def test_the_runner_refuses_every_non_scanned_state(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    for scan_status, processing in (
        ("pending", "pending"),
        ("failed", "failed"),
        ("quarantined", "pending"),
        ("stored", "pending"),  # legacy pre-scanner rows: refused too
    ):
        conversation = await _conversation_with_image(
            db, tenant_id, scan_status=scan_status, processing_status=processing
        )
        _turns, image_key, _audio = await AgentRunner._conversation_context(
            db, tenant_id, conversation.id
        )
        assert image_key is None, f"scan_status={scan_status} must not egress"


async def test_the_runner_admits_a_scanned_image(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation_with_image(db, tenant_id, scan_status="scanned")

    _turns, image_key, _audio = await AgentRunner._conversation_context(
        db, tenant_id, conversation.id
    )

    assert image_key == STORAGE_KEY


# --------------------------------------------- coordinator (no provider) ---


async def test_the_coordinator_never_calls_the_provider_without_a_url(db, tenant_ctx, monkeypatch):
    """The graceful degradation, end to end: no minted URL → no provider call.

    The hook hands the coordinator an empty `image_urls` for a pending image;
    run_customer_turn must skip the vision pass entirely and still answer.
    """
    vision_calls: list[str] = []

    async def no_vision(session, tenant_id, *, image_url, text_hint=None):
        vision_calls.append(image_url)  # pragma: no cover — must never run
        raise AssertionError("the provider must not be called without a scanned image")

    monkeypatch.setattr(turn_module, "run_vision_match", no_vision)
    runner = FakeRunner(AgentRunResult(content="شفت الرسالة", guardrail_decision="allow"))

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Turn Egress Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )

    outcome = await run_customer_turn(
        db,
        TurnInput(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=conversation.id,
            agent_id=uuid.uuid4(),
            body="دي الصورة",
            content_type="image",
            attachments=[("image/png", STORAGE_KEY)],
            image_urls={},  # what the hook mints for a pending image
        ),
        runner=runner,
    )

    assert vision_calls == []
    assert outcome.reply == "شفت الرسالة"  # the turn answered without vision


# ------------------------------------------------ unconfigured end to end --


async def test_without_a_scanner_an_ingested_image_never_passes_the_gate(
    db, tenant_ctx, monkeypatch
):
    """The full fail-closed loop: real ingest (no clamd) → pending → no URL.

    The bytes ARE durably stored; the gate still refuses them, because
    "stored but never scanned" is exactly the state ADR-062 refuses.
    """
    tenant_id = tenant_ctx.tenant_id
    _set_scanner(monkeypatch)  # pin: no scanner configured
    await _agent(db, tenant_id)

    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", "wa-egress-001", name="Egress WA"
    )
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        media_url=MEDIA_URL,
        media_type="image",
        channel_message_id="wamid-egress-001",
        media_storage=FakeStorage(),
    )
    attachments = await MediaService.list_for_message(db, tenant_id, message.id)
    assert attachments[0].scan_status == "pending"

    captured = _capture_turn(monkeypatch)
    _patch_signed_urls(monkeypatch)
    await maybe_auto_reply(db, tenant_id, conversation.id)

    assert captured[0].image_urls == {}
