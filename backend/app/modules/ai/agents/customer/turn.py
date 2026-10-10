"""Turn coordinator (spec §8, M2) — one customer turn, start to finish.

Wires the tested M2 foundations into one ordered flow and owns the
DECISIONS between them:

    intake → state load → referents → vision → runner → grounding → patch

* The state row is read BEFORE the runner so referents resolve against what
  was shown so far, and patched AFTER it with optimistic concurrency — a
  concurrent turn on the same conversation cannot be clobbered.
* The vision match runs on the FIRST photo only (v1): two photos in one
  turn is an ambiguity the reply should ask about, not guess across.
* Every number the draft uses must trace to a tool result (grounding §12);
  a failed check yields NO reply — the caller sends the safe fallback.
  v1 deliberately does NOT regenerate: a second model call burns budget on
  a reply the deterministic check may bounce again.
* The customer's media never reaches the pipeline as a storage key: the
  caller mints provider-fetchable URLs (Response Resolver's job) and passes
  the mapping in. The agent accepts no tenant credentials (§9).

The runner is injectable — tests substitute a fake; production uses the
platform AgentRunner.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.agents.customer.grounding import check_grounding
from app.modules.ai.agents.customer.intake import InboundTurn, build_turn
from app.modules.ai.agents.customer.ledger import facts_from_tool_calls
from app.modules.ai.agents.customer.referents import (
    Referent,
    normalize_arabic,
    resolve_referent,
)
from app.modules.ai.agents.customer.state import (
    StaleStateError,
    apply_patch,
    load_state,
)
from app.modules.ai.agents.customer.vision.pipeline import run_vision_match
from app.modules.ai.agents.customer.vision.schemas import MatchResult
from app.modules.ai.runtime import AgentRunner, AgentRunResult

logger = logging.getLogger(__name__)

#: Wall-clock ceiling for the whole turn (deadline/budgets, spec §8). The
#: coordinator cannot interrupt the runner mid-call; it stops spending
#: AFTER the first model call (no regeneration, no second vision pass).
TURN_DEADLINE_SECONDS = 45.0

#: Photos processed per turn — the rest are acknowledged, not interpreted.
MAX_PHOTOS_PER_TURN = 1


@dataclass(slots=True)
class TurnInput:
    """Everything the coordinator needs, owned by the caller (the hook)."""

    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    agent_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    # The message this turn answers — keys the runner's tool-call idempotency.
    inbound_message_id: uuid.UUID | None = None
    # --- raw message fields, passed straight to build_turn ---
    body: str | None = None
    content_type: str | None = None
    attachments: list[tuple[str, str | None]] = field(default_factory=list)
    transcript: str | None = None
    # storage_key → provider-fetchable URL, minted OUTSIDE the agent (§9).
    image_urls: dict[str, str] = field(default_factory=dict)
    # Retrieved knowledge snippets, owned by the caller (the hook); merged
    # with the system-owned context lines into the runner's untrusted block.
    knowledge_context: str | None = None


@dataclass(slots=True)
class TurnOutcome:
    """What the turn decided — the caller's reply surface and the book."""

    reply: str | None
    media: list[dict] = field(default_factory=list)
    state_version: int = 0
    vision: list[dict] = field(default_factory=list)
    referent: Referent | None = None
    grounding: str = "skipped_no_facts"
    blocked_reason: str | None = None
    deadline_exceeded: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    run_id: uuid.UUID | None = None
    # §37: a handover this turn REQUIRES, as the reason vocabulary of
    # ai_handovers. Set when the customer asked for a person — the caller
    # (the hook) owns the handover write, because it owns the conversation.
    handover_reason: str | None = None


#: Normalized markers that SIGNAL a pointing attempt — matched to decide
#: whether the ask-don't-guess line belongs in the context. A marker with no
#: resolved referent (out of range, or nothing shown yet) is exactly the case
#: the reply must ask about, never guess across.
_POINTING_MARKERS = ("الاول", "التاني", "التالت", "اللي فات", "الاخير", "ده", "دي")

#: §37: "اتكلم مع حد" is a handover, not a question. Two parts must both be
#: present in the customer's own words — something they want, and a person to
#: want it from — so a product named "موظف" in passing or a bare "عايز" does
#: not fire. The list is deliberately forgiving on phrasing and strict on
#: grammar: a false positive costs one queue row a human can dismiss, while a
#: false negative leaves the customer talking to the thing they just asked to
#: stop talking to. Matched against `normalize_arabic` output, so alef/yeh/
#: teh-marbuta spelling variants and harakat are already folded.
_HUMAN_REQUEST_WANTING = (
    "اتكلم",
    "اكلم",
    "تكلم",
    "كلام",
    "عايز",
    "عاوز",
    "عيز",
    "اريد",
    "ابغي",
    "نفسي",
    "وصلني",
    "كلمني",
    "speak",
    "talk",
    "need",
)
_HUMAN_REQUEST_PERSON = (
    "موظف",
    "مسؤول",
    "مسئول",
    "انسان",
    "ادمي",
    "بشر",
    "خدمه العملاء",
    "فريق",
    "human",
    "person",
    "representative",
    "agent",
    "staff",
)

#: What the customer hears when they ask for a person. Fixed words: it states
#: no price, no product and no promise beyond the handover itself, and it
#: replaces the model call rather than being checked after one.
_HUMAN_REQUEST_ACK = "حاضر، هوصّلك على شخص من الفريق — هو يكمل معاك من هنا."


def wants_human_request(text: str | None) -> bool:
    """True when the customer asked, in their own words, for a human."""
    if not text:
        return False
    normalized = normalize_arabic(text)
    return any(want in normalized for want in _HUMAN_REQUEST_WANTING) and any(
        person in normalized for person in _HUMAN_REQUEST_PERSON
    )


def _context_lines(
    turn: InboundTurn,
    state_shown: list[str],
    referent: Referent | None,
    vision_results: list[MatchResult],
    skipped_photos: int,
) -> str | None:
    """The system-owned context block, or None when there is nothing to say.

    System-generated facts only (state, vision) — never customer text, which
    rides the user message where it belongs (§132 untrusted zone).
    """
    lines: list[str] = []
    if state_shown:
        lines.append("المنتجات اللي اعرضت على العميل بالترتيب: " + ", ".join(state_shown))
    if referent is not None:
        lines.append(
            f"العميل يقصد العنصر رقم {referent.position} (معرّف المنتج: {referent.product_id})."
        )
    elif not vision_results and any(
        marker in normalize_arabic(turn.text or "") for marker in _POINTING_MARKERS
    ):
        # No vision result means no photo to be the "ده" — a bare pointing
        # marker with nothing it can resolve to is the ask, never a guess.
        lines.append(
            "العميل أشار بعلامة ترتيب لكن مفيش عنصر مطابق في اللي اتعرض — اسأله بدل ما تخمّن."
        )
    for result in vision_results:
        top = ", ".join(
            f"{c['title']} (id={c['product_id']}, verified={c['verified']})"
            for c in result.candidates[:3]
        )
        lines.append(
            f"نتيجة تحليل الصورة: ثقة={result.confidence.value}"
            f"{' سبب=' + result.reason if result.reason else ''}"
            f"{'; مرشحات: ' + top if top else ''}"
        )
    if skipped_photos:
        lines.append(f"فيه {skipped_photos} صورة إضافية لم تُحلَّل في هذه الدورة.")
    if turn.has_voice and not turn.voice_transcript:
        lines.append("بعت عميل رسالة صوتية ولسه متنسّختش — اعرض عليه تكتبها.")
    if turn.other_media:
        lines.append("فيه مرفق غير متاح للتحليل (ملف/فيديو/موقع) — اعترف بيه فقط.")
    return "\n".join(lines) if lines else None


def _message_text(turn: InboundTurn, vision_used: bool) -> str:
    """The user-message slot: the customer's own words, or a bare marker."""
    if turn.text:
        return turn.text
    if vision_used:
        return "بعت لي صورة منتج."
    if turn.has_voice:
        return "بعت لي رسالة صوتية."
    if turn.other_media:
        return "بعت لي مرفق."
    return ""


async def run_customer_turn(
    session: AsyncSession,
    params: TurnInput,
    *,
    runner: AgentRunner | None = None,
    deadline_seconds: float = TURN_DEADLINE_SECONDS,
) -> TurnOutcome:
    """One customer turn through the whole M2 stack."""
    started = time.monotonic()
    _runner = runner or AgentRunner()

    turn = build_turn(
        body=params.body,
        content_type=params.content_type,
        attachments=params.attachments,
        transcript=params.transcript,
    )

    state = await load_state(session, params.tenant_id, params.conversation_id)
    state_version = state.state_version if state else 0

    # §37: a customer who asks for a person gets one. This exits BEFORE the
    # vision pass and the model call — no state patch, no budget spent, no
    # answer improvised. `handover_reason` is the hook's instruction to move
    # the conversation; the ack only tells the customer it happened.
    asked_words = turn.text or turn.voice_transcript
    if wants_human_request(asked_words):
        return TurnOutcome(
            reply=_HUMAN_REQUEST_ACK,
            state_version=state_version,
            handover_reason="customer_request",
        )

    shown = list(state.shown_items) if state else []
    referent = resolve_referent(turn.text or "", shown)

    # Vision: first photo only (v1); URLs are minted by the caller, keys
    # without one are acknowledged as unprocessed rather than dropped.
    vision_results: list[MatchResult] = []
    processed = 0
    for key in turn.image_keys[:MAX_PHOTOS_PER_TURN]:
        url = params.image_urls.get(key)
        if not url:
            continue
        processed += 1
        vision_results.append(
            await run_vision_match(
                session,
                params.tenant_id,
                image_url=url,
                text_hint=turn.text_hint(),
            )
        )
    skipped_photos = len(turn.image_keys) - processed

    context = _context_lines(turn, shown, referent, vision_results, skipped_photos)
    user_message = _message_text(turn, bool(vision_results))
    if not user_message and not context:
        # Nothing actionable arrived (e.g. an empty body after stripping).
        return TurnOutcome(
            reply=None,
            state_version=state_version,
            blocked_reason="empty_turn",
        )

    # P1-10: the customer's own message may carry a quote's confirmation
    # code. Matched HERE, server-side, against the inbound text — a model
    # sentence claiming "the customer confirmed" changes nothing. The id of
    # a confirmed quote flows to the tools through the runtime's server-bound
    # context, so create_order can only execute lines the customer typed a
    # code for.
    confirmed_quote_id: uuid.UUID | None = None
    quote_line: str | None = None
    if params.customer_id is not None:
        from app.modules.ai.agents.customer.confirmation import live_quote, match_confirmation

        matched = await match_confirmation(
            session,
            params.tenant_id,
            conversation_id=params.conversation_id,
            customer_id=params.customer_id,
            text=turn.text,
        )
        if matched is not None:
            confirmed_quote_id = matched.id
            quote_line = (
                f"العميل أكّد الطلب (كود: {matched.code}) — "
                "نادي create_order لتنفيذ البنود المؤكدة."
            )
        else:
            live = await live_quote(
                session,
                params.tenant_id,
                conversation_id=params.conversation_id,
                customer_id=params.customer_id,
            )
            if live is not None and live.status == "pending":
                quote_line = (
                    f"فيه عرض سعر مستني تأكيد العميل (كود التأكيد: {live.code}). "
                    "الطلب لم ينفذ — لازم العميل يبعت الكود بنفسه الأول."
                )

    # The hook's retrieved snippets ride FIRST; the system-owned context
    # lines (state, referents, vision) follow — both stay OUTSIDE the system
    # prompt (§132 untrusted zone).
    merged_context = (
        "\n".join(part for part in (params.knowledge_context, context, quote_line) if part)
        or None
    )

    result: AgentRunResult = await _runner.run(
        session,
        params.tenant_id,
        agent_id=params.agent_id,
        conversation_id=params.conversation_id,
        inbound_message_id=params.inbound_message_id,
        user_message=user_message,
        customer_id=params.customer_id,
        knowledge_context=merged_context,
        confirmed_quote_id=confirmed_quote_id,
    )

    deadline_exceeded = (time.monotonic() - started) > deadline_seconds
    grounding = "skipped_no_facts"
    reply: str | None = result.content
    blocked_reason: str | None = None

    if result.guardrail_decision != "allow":
        reply = None
        blocked_reason = f"guardrail:{result.guardrail_reason}"
    elif result.content:
        facts = facts_from_tool_calls(result.tool_calls_made)
        if not facts:
            # Skip contract: the unsourced-claim guardrail owns this case.
            grounding = "skipped_no_facts"
        else:
            reason = check_grounding(result.content, facts)
            if reason is None:
                grounding = "ok"
            elif deadline_exceeded:
                grounding = "failed"
                reply = None
                blocked_reason = f"grounding:{reason}"
            else:
                grounding = "failed"
                reply = None
                blocked_reason = f"grounding:{reason}"

    # State patch: what THIS run showed or referenced, append-only. A stale
    # version means a concurrent turn moved the row — the lists are append-
    # only and deduped, so re-applying against a fresh read is idempotent.
    new_shown = list(result.shown_product_ids)
    for vr in vision_results:
        new_shown.extend(c["product_id"] for c in vr.candidates if c.get("verified"))
    new_media = [str(m["image_id"]) for m in result.media if m.get("image_id") is not None]
    final_version = state_version
    if new_shown or new_media:
        patch: dict[str, list[str]] = {}
        if new_shown:
            patch["shown_items"] = new_shown
        if new_media:
            patch["sent_media"] = new_media
        try:
            patched = await apply_patch(
                session,
                params.tenant_id,
                params.conversation_id,
                patch,
                expected_version=state_version,
            )
        except StaleStateError:
            patched = await apply_patch(session, params.tenant_id, params.conversation_id, patch)
        final_version = patched.state_version

    return TurnOutcome(
        reply=reply,
        media=result.media,
        state_version=final_version,
        vision=[
            {
                "confidence": vr.confidence.value,
                "reason": vr.reason,
                "candidates": vr.candidates,
            }
            for vr in vision_results
        ],
        referent=referent,
        grounding=grounding,
        blocked_reason=blocked_reason,
        deadline_exceeded=deadline_exceeded,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        run_id=result.run_id,
    )
