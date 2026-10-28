"""Turn coordinator tests (spec §8, M2) — the ordered flow, no LLM.

The runner is a fake that records what it was called with; the vision match
is stubbed (the four vision stages carry their own tests). What IS real
here: state (optimistic patching against the DB), referents, the ledger,
and the grounding check — the coordinator's own decisions are the subject.
"""

from __future__ import annotations

import uuid

from app.modules.ai.agents.customer import turn as turn_module
from app.modules.ai.agents.customer.state import apply_patch
from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.agents.customer.vision.schemas import Confidence, MatchResult
from app.modules.ai.runtime import AgentRunResult

PRODUCT_A = str(uuid.uuid4())
PRODUCT_B = str(uuid.uuid4())


class FakeRunner:
    """Records the call and replays a canned AgentRunResult."""

    def __init__(self, result: AgentRunResult, *, sleep: float = 0.0):
        self.result = result
        self.sleep = sleep
        self.calls: list[dict] = []

    async def run(self, session, tenant_id, **kwargs):
        import asyncio

        self.calls.append({"tenant_id": tenant_id, **kwargs})
        if self.sleep:
            await asyncio.sleep(self.sleep)
        return self.result


def _result(
    content: str | None = "تمام، وصلت",
    *,
    tool_calls: list[dict] | None = None,
    media: list[dict] | None = None,
    shown: list[str] | None = None,
    guardrail: str = "allow",
) -> AgentRunResult:
    return AgentRunResult(
        content=content,
        tool_calls_made=tool_calls or [],
        media=media or [],
        shown_product_ids=shown or [],
        guardrail_decision=guardrail,
        guardrail_reason=None if guardrail == "allow" else "policy",
    )


def _vision(candidates: list[dict], confidence=Confidence.MEDIUM) -> MatchResult:
    return MatchResult(confidence=confidence, candidates=candidates, reason="match")


async def _conversation(db, tenant_ctx) -> uuid.UUID:
    """A real customer + conversation row: state patches satisfy the FK."""
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Turn Customer")
    db.add(customer)
    await db.flush()
    conversation = Conversation(
        tenant_id=tenant_ctx.tenant_id,
        customer_id=customer.id,
        channel="webchat",
    )
    db.add(conversation)
    await db.flush()
    return conversation.id


def _params(db, tenant_ctx, **overrides) -> TurnInput:
    defaults = dict(
        tenant_id=tenant_ctx.tenant_id,
        conversation_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        body="عايز أعرف السعر",
    )
    defaults.update(overrides)
    return TurnInput(**defaults)


async def test_empty_turn_short_circuits_without_calling_the_runner(db, tenant_ctx):
    runner = FakeRunner(_result())
    outcome = await run_customer_turn(db, _params(db, tenant_ctx, body=None), runner=runner)
    assert outcome.reply is None
    assert outcome.blocked_reason == "empty_turn"
    assert runner.calls == []


async def _photo_classifier(session, tid, url):
    from app.modules.ai.agents.customer.vision.schemas import ImageKind

    return ImageKind.PRODUCT


async def test_photo_turn_runs_vision_and_shows_verified_products(db, tenant_ctx, monkeypatch):
    captured: dict = {}

    async def fake_vision(session, tenant_id, *, image_url, text_hint=None):
        captured["image_url"] = image_url
        captured["text_hint"] = text_hint
        return _vision(
            [
                {
                    "product_id": PRODUCT_A,
                    "title": "عباية سوداء",
                    "verified": True,
                    "available_variants": 2,
                }
            ]
        )

    monkeypatch.setattr(turn_module, "run_vision_match", fake_vision)
    runner = FakeRunner(_result())
    conversation_id = await _conversation(db, tenant_ctx)
    outcome = await run_customer_turn(
        db,
        _params(
            db,
            tenant_ctx,
            conversation_id=conversation_id,
            body="دي الصورة",
            attachments=[("image/png", "uploads/photo-1.png")],
            image_urls={"uploads/photo-1.png": "https://cdn.test/photo-1.png"},
        ),
        runner=runner,
        image_classifier=_photo_classifier,
    )

    assert captured["image_url"] == "https://cdn.test/photo-1.png"
    assert captured["text_hint"] == "دي الصورة"
    # The vision result rode the context — the model sees the match. The
    # verified product does NOT enter shown state here: candidates become
    # "shown" only when get_product_photos actually delivers their images,
    # so the numbered list never contains anything the customer never saw.
    assert PRODUCT_A in runner.calls[0]["context_lines"]
    assert outcome.state_version == 0
    assert outcome.vision[0]["candidates"][0]["product_id"] == PRODUCT_A


async def test_photo_without_a_minted_url_is_counted_not_interpreted(db, tenant_ctx, monkeypatch):
    seen: list = []

    async def fake_vision(session, tenant_id, *, image_url, text_hint=None):
        seen.append(image_url)
        return _vision([])

    monkeypatch.setattr(turn_module, "run_vision_match", fake_vision)
    runner = FakeRunner(_result())
    outcome = await run_customer_turn(
        db,
        _params(
            db,
            tenant_ctx,
            body=None,
            attachments=[
                ("image/png", "uploads/a.png"),
                ("image/png", "uploads/b.png"),
            ],
            image_urls={},  # nothing minted yet
        ),
        runner=runner,
    )
    assert seen == []  # nothing was sent to the vision pipeline
    assert outcome.vision == []
    assert "2 صورة" in runner.calls[0]["context_lines"]


async def test_ordinal_referent_resolves_against_shown_items(db, tenant_ctx):
    """The model resolves "التاني" itself — the context hands it the numbered
    shown list, ids included, and nothing else decides for it."""
    conversation_id = await _conversation(db, tenant_ctx)
    await apply_patch(
        db,
        tenant_ctx.tenant_id,
        conversation_id,
        {"shown_items": [PRODUCT_A, PRODUCT_B]},
    )
    runner = FakeRunner(_result())
    await run_customer_turn(
        db,
        _params(
            db,
            tenant_ctx,
            conversation_id=conversation_id,
            body="ابعت لي صورة التاني",
        ),
        runner=runner,
    )
    context = runner.calls[0]["context_lines"]
    first = context.index("1. ")
    second = context.index("2. ")
    assert context.index(PRODUCT_A) < second < context.index(PRODUCT_B)
    assert first < second


async def test_ordinal_beyond_shown_asks_instead_of_guessing(db, tenant_ctx):
    """A list with one item cannot ground a "التالت" — the model sees exactly
    that (one numbered line) and the prompt's rule makes it ask."""
    conversation_id = await _conversation(db, tenant_ctx)
    await apply_patch(
        db,
        tenant_ctx.tenant_id,
        conversation_id,
        {"shown_items": [PRODUCT_A]},
    )
    runner = FakeRunner(_result())
    await run_customer_turn(
        db,
        _params(db, tenant_ctx, conversation_id=conversation_id, body="ابعت التالت"),
        runner=runner,
    )
    context = runner.calls[0]["context_lines"]
    assert "1. " in context
    assert "\n2. " not in context  # there is no second line to point at


async def test_ungrounded_numeral_blocks_the_reply(db, tenant_ctx):
    runner = FakeRunner(
        _result(
            content="السعر 199 جنيه والخصم 30%",
            tool_calls=[{"name": "get_product", "status": "ok", "result": {"price": "149.00"}}],
        )
    )
    outcome = await run_customer_turn(db, _params(db, tenant_ctx), runner=runner)
    assert outcome.reply is None
    assert outcome.grounding == "failed"
    assert outcome.blocked_reason is not None
    assert "199" in outcome.blocked_reason


async def test_grounded_numerals_pass_through(db, tenant_ctx):
    runner = FakeRunner(
        _result(
            content="السعر 149.00 والكمية 2",
            tool_calls=[
                {
                    "name": "search_catalog",
                    "status": "ok",
                    "args": {"query": "widget"},
                    "result": {"price": "149.00", "quantity": 2},
                }
            ],
        )
    )
    outcome = await run_customer_turn(db, _params(db, tenant_ctx), runner=runner)
    assert outcome.reply is not None
    assert outcome.grounding == "ok"


# ---- numbers with NO tool behind them (the skipped_no_facts gap) -----------
#
# The financial-claim guardrail only recognises price / stock / money wording,
# and grounding only runs when a tool returned facts. A policy or schedule
# figure in a run with no tool used to reach the customer untouched.


async def test_a_policy_figure_with_no_tool_behind_it_is_withheld(db, tenant_ctx):
    runner = FakeRunner(_result(content="الاسترجاع خلال 14 يوم من الاستلام"))
    outcome = await run_customer_turn(
        db, _params(db, tenant_ctx, body="ينفع ارجع المنتج؟"), runner=runner
    )
    assert outcome.reply is None
    assert outcome.grounding == "failed"
    assert outcome.blocked_reason == "grounding:unsourced numeral: 14"


async def test_a_schedule_figure_with_no_tool_behind_it_is_withheld(db, tenant_ctx):
    runner = FakeRunner(_result(content="بنقفل الساعة 10 بالليل"))
    outcome = await run_customer_turn(
        db, _params(db, tenant_ctx, body="بتقفلوا امتى؟"), runner=runner
    )
    assert outcome.reply is None
    assert outcome.blocked_reason == "grounding:unsourced numeral: 10"


async def test_the_customers_own_number_may_be_echoed_without_a_tool(db, tenant_ctx):
    """ "عايز 2 تيشرت" -> "تمام، 2 تيشرت" is a confirmation, not a claim."""
    runner = FakeRunner(_result(content="تمام، 2 تيشرت. هحولك لحد من الفريق يكمل معاك."))
    outcome = await run_customer_turn(
        db, _params(db, tenant_ctx, body="عايز 2 تيشرت"), runner=runner
    )
    assert outcome.reply is not None
    assert outcome.blocked_reason is None


async def test_an_arabic_indic_number_in_the_customers_message_covers_the_echo(db, tenant_ctx):
    runner = FakeRunner(_result(content="تمام، 2 تيشرت"))
    outcome = await run_customer_turn(
        db, _params(db, tenant_ctx, body="عايز ٢ تيشرت"), runner=runner
    )
    assert outcome.reply is not None


async def test_a_reply_without_numbers_and_without_a_tool_is_unaffected(db, tenant_ctx):
    runner = FakeRunner(_result(content="ممكن توضحلي أكتر تقصد أنهي موديل؟"))
    outcome = await run_customer_turn(db, _params(db, tenant_ctx), runner=runner)
    assert outcome.reply is not None
    assert outcome.grounding == "skipped_no_facts"


async def test_a_successful_tool_with_no_figures_is_still_a_source(db, tenant_ctx):
    """An empty search RAN: "لقيت 0 نتيجة" is the tool's own answer, so the
    new check must not silence it."""
    runner = FakeRunner(
        _result(
            content="مفيش مطابق ل 0 نتيجة، وضحلي أكتر",
            tool_calls=[{"name": "search_catalog", "status": "ok", "result": {"results": []}}],
        )
    )
    outcome = await run_customer_turn(db, _params(db, tenant_ctx), runner=runner)
    assert outcome.reply is not None


async def test_a_failed_tool_is_not_a_source_for_a_number(db, tenant_ctx):
    runner = FakeRunner(
        _result(
            content="الاسترجاع خلال 14 يوم",
            tool_calls=[{"name": "get_store_info", "status": "error", "result": {"error": "x"}}],
        )
    )
    outcome = await run_customer_turn(db, _params(db, tenant_ctx), runner=runner)
    assert outcome.reply is None
    assert outcome.blocked_reason == "grounding:unsourced numeral: 14"


async def test_voice_without_transcript_is_surfaced_not_hidden(db, tenant_ctx):
    runner = FakeRunner(_result())
    await run_customer_turn(
        db,
        _params(
            db,
            tenant_ctx,
            body=None,
            content_type="voice",
            transcript=None,
        ),
        runner=runner,
    )
    assert "صوتية" in runner.calls[0]["context_lines"]


async def test_other_media_is_acknowledged(db, tenant_ctx):
    runner = FakeRunner(_result())
    await run_customer_turn(
        db,
        _params(db, tenant_ctx, body=None, content_type="location"),
        runner=runner,
    )
    assert "اعترف بيه" in runner.calls[0]["context_lines"]


async def test_context_carries_the_weekday_and_channel(db, tenant_ctx):
    """The model cannot say "بعد يومين" or match the channel's tone without
    knowing what day it is and where the customer is talking — and the
    weekday carries NO digits, so grounding never blocks the phrasing."""
    runner = FakeRunner(_result())
    await run_customer_turn(
        db,
        _params(
            db,
            tenant_ctx,
            body="السلام عليكم",
            channel="webchat",
            tenant_timezone="Africa/Cairo",
        ),
        runner=runner,
    )
    context = runner.calls[0]["context_lines"]
    assert "النهارده" in context
    weekdays = ("الاثنين", "الثلاثاء", "الاربعاء", "الخميس", "الجمعة", "السبت", "الاحد")
    assert any(day in context for day in weekdays)
    assert "القناة: webchat" in context


async def test_a_broken_timezone_degrades_to_utc_without_failing(db, tenant_ctx):
    runner = FakeRunner(_result())
    outcome = await run_customer_turn(
        db,
        _params(db, tenant_ctx, body="السلام عليكم", tenant_timezone="Not/AZone"),
        runner=runner,
    )
    assert "النهارده" in runner.calls[0]["context_lines"]
    assert outcome.blocked_reason is None


async def test_guardrail_block_yields_no_reply(db, tenant_ctx):
    runner = FakeRunner(_result(guardrail="deny"))
    outcome = await run_customer_turn(db, _params(db, tenant_ctx), runner=runner)
    assert outcome.reply is None
    assert outcome.blocked_reason == "guardrail:policy"


async def test_state_patch_appends_and_dedupes_across_turns(db, tenant_ctx):
    conversation_id = await _conversation(db, tenant_ctx)
    first = FakeRunner(_result(shown=[PRODUCT_A], media=[{"image_id": "img-1"}]))
    await run_customer_turn(
        db, _params(db, tenant_ctx, conversation_id=conversation_id), runner=first
    )
    second = FakeRunner(_result(shown=[PRODUCT_A, PRODUCT_B], media=[{"image_id": "img-1"}]))
    outcome = await run_customer_turn(
        db,
        _params(db, tenant_ctx, conversation_id=conversation_id),
        runner=second,
    )
    assert outcome.state_version == 2  # the second turn ADDED something
    from app.modules.ai.agents.customer.state import load_state

    state = await load_state(db, tenant_ctx.tenant_id, conversation_id)
    assert state.shown_items == [PRODUCT_A, PRODUCT_B]
    assert state.sent_media == ["img-1"]


async def test_deadline_exceeded_is_surfaced(db, tenant_ctx):
    runner = FakeRunner(_result(), sleep=0.05)
    outcome = await run_customer_turn(
        db, _params(db, tenant_ctx), runner=runner, deadline_seconds=0.01
    )
    assert outcome.deadline_exceeded is True


def test_unsourced_numerals_allows_zero_and_the_customers_own_numbers() -> None:
    from app.modules.ai.agents.customer.grounding import check_unsourced_numerals

    assert check_unsourced_numerals("ملقتش حاجة، 0 نتيجة.", "عندكم بنطلون؟") is None
    assert check_unsourced_numerals("تمام، 2 تيشرت", "عايز 2 تيشرت") is None
    assert check_unsourced_numerals("تمام، ٢ تيشرت", "عايز 2 تيشرت") is None
    assert check_unsourced_numerals("الاسترجاع خلال 14 يوم", "ينفع ارجع؟") == (
        "unsourced numeral: 14"
    )
    # 0 is allowed, but only 0: it must not open the door to 10 or 0.5.
    assert check_unsourced_numerals("بنقفل 10", "امتى؟") == "unsourced numeral: 10"
    assert check_unsourced_numerals("خصم 0.5", "امتى؟") == "unsourced numeral: 0.5"
