"""Turn coordinator — one customer turn, start to finish.

Wires the foundations into one ordered flow and owns the DECISIONS between
them:

    intake → state load → vision → runner → grounding → patch

Scope cut (2026-10-18): intent is the MODEL's job. The old pre-model keyword
exits (human-request detection, the referent resolver) are gone — a keyword
that matches inside a correctly-understood message forced the whole turn down
the wrong path. The model reads the same context (numbered shown items,
customer name, vision results) and decides: answer, ask, or escalate via the
handover_to_human tool.

What stayed deterministic is NOT intent: the image pre-classification gate
(parked — voice/images have their own session), the grounding check, and the
state patch. Integrity gates block wrong replies; they never pick a path.

* The state row is read BEFORE the runner so context reflects what was shown
  so far, and patched AFTER it with optimistic concurrency.
* The vision match runs on the FIRST photo only (v1).
* Every number the draft uses must trace to a tool result (grounding); a
  failed check yields NO reply — the hook records a handover and the
  customer hears nothing from the agent. That silence is the DECIDED
  product behavior (2026-10-18): a problem goes to a human, and silence
  beats a wrong or improvised message.
* The customer's media never reaches the pipeline as a storage key: the
  caller mints provider-fetchable URLs and passes the mapping in.

The runner is injectable — tests substitute a fake; production uses the
platform AgentRunner.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.agents.customer.grounding import (
    check_grounding,
    check_unsourced_numerals,
)
from app.modules.ai.agents.customer.intake import InboundTurn, build_turn
from app.modules.ai.agents.customer.ledger import facts_from_tool_calls
from app.modules.ai.agents.customer.state import (
    StaleStateError,
    apply_patch,
    load_state,
)
from app.modules.ai.agents.customer.vision.pipeline import run_vision_match
from app.modules.ai.agents.customer.vision.schemas import ImageKind, MatchResult
from app.modules.ai.runtime import AgentRunner, AgentRunResult

#: The server-side classifier: (session, tenant_id, image_url) → kind. The
#: default resolves the conversation model and asks it one closed-vocabulary
#: question BEFORE any embedding/rerank egress — a payment proof must never
#: reach the vision pipeline just because the model never proposed the tool.
ImageClassifier = __import__("typing").Callable


_IMAGE_CLASSIFY_PROMPT = (
    "صنّف الصورة دي بكلمة واحدة من القائمة دي بس: "
    "product أو payment_proof أو complaint أو size_chart أو other. "
    "اكتب الكلمة الإنجليزي بس من غير أي كلام تاني."
)

#: Kinds that mean a human handles the image — §12.5's fail-closed rule, now
#: enforced server-side BEFORE any embedding/rerank egress. (Parked scope:
#: voice/images keep their own session; this gate stays as-is.)
_SENSITIVE_IMAGE_KINDS = frozenset({ImageKind.PAYMENT_PROOF, ImageKind.COMPLAINT})

_SENSITIVE_IMAGE_ACK = (
    "وصلتني الصورة، وحوّلتها لفريق العمل يتابعوا معاك فيها في أقرب وقت."
)


async def _default_classify_image_kind(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    image_url: str,
    *,
    gateway,
    alias: str,
) -> ImageKind:
    """One closed-vocabulary classification call through the governed gateway.

    Failure degrades to OTHER (no retrieval; the model still sees the image
    and answers) — never to PRODUCT, which would egress an unclassified photo
    to the embedding provider."""

    try:
        result = await gateway.chat(
            session,
            tenant_id,
            alias=alias,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _IMAGE_CLASSIFY_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            temperature=0.0,
            max_tokens=16,
        )
        raw = (result.content or "").strip().lower()
        for kind in ImageKind:
            if kind.value in raw:
                return kind
        return ImageKind.OTHER
    except Exception:  # noqa: BLE001 — the classify call must never fail the turn
        logger.warning(
            "ai.image_classify_failed — degrading to unclassified (no retrieval)",
            exc_info=True,
        )
        return ImageKind.OTHER


logger = logging.getLogger(__name__)

#: Wall-clock ceiling for the whole turn (deadline/budgets, spec §8). The
#: coordinator cannot interrupt the runner mid-call; it stops spending
#: AFTER the first model call (no regeneration, no second vision pass).
TURN_DEADLINE_SECONDS = 45.0

#: Photos processed per turn — the rest are acknowledged, not interpreted.
MAX_PHOTOS_PER_TURN = 1

#: datetime.weekday() → Arabic day name. No digits, by design — see the
#: context line above.
def _today_weekday(timezone: str | None) -> int:
    """The store's weekday index: the tenant timezone when usable, UTC
    otherwise — an unparseable timezone must not fail the turn."""
    from zoneinfo import ZoneInfo

    try:
        if timezone:
            return datetime.now(ZoneInfo(timezone)).weekday()
    except Exception:  # noqa: BLE001 — a bad tz string degrades to UTC
        pass
    return datetime.now(UTC).weekday()


_ARABIC_WEEKDAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الاربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الاحد",
}


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
    # Store-owned facts about WHO the agent is talking to. The old get_customer
    # tool is gone; the name/locale ride the context instead — the model never
    # spends a call to learn the customer's name.
    customer_name: str | None = None
    customer_locale: str | None = None
    # The channel the customer is talking on — "الشحن بيوصل فين" and tone
    # both depend on it, and the model has no other way to know.
    channel: str | None = None
    # The store's IANA timezone (tenants.timezone): the weekday line is
    # computed HERE so "today" is the store's today, not UTC's.
    tenant_timezone: str | None = None
    # Direct-Omni input: the caller determined the newest message's audio will
    # ride the model call itself (scanner-cleared, supported format, flag on).
    # When True the "voice not transcribed yet — ask them to type" context
    # line must NOT fire: the model is about to HEAR the customer, and telling
    # it the voice was unintelligible contradicts the bytes in its own payload.
    audio_rides: bool = False


@dataclass(slots=True)
class TurnOutcome:
    """What the turn decided — the caller's reply surface and the book."""

    reply: str | None
    media: list[dict] = field(default_factory=list)
    state_version: int = 0
    vision: list[dict] = field(default_factory=list)
    grounding: str = "skipped_no_facts"
    blocked_reason: str | None = None
    deadline_exceeded: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    run_id: uuid.UUID | None = None
    # A handover this turn REQUIRES (policy-level, e.g. a sensitive image).
    # Model-initiated handovers are written by the handover_to_human tool
    # itself; this field is only for exits the model never sees.
    handover_reason: str | None = None
    handover_note: str | None = None


#: §12.5: the classifier's handoff verdicts, exactly as they surface in a
#: failed tool call's error string. Matched literally, by value: the mapping
#: from "the model called find_product_by_image on a payment receipt" to "a
#: human must take this" must not depend on the model choosing to act on the
#: error text — the coordinator decides, deterministically.
_IMAGE_HANDOFF_REASONS = frozenset(
    {
        "payment_proof_requires_human",
        "complaint_requires_human",
    }
)


def _image_handoff_reason(tool_calls: list[dict]) -> str | None:
    """The deterministic handover for a non-product image, or None.

    The tool already refuses to run the pipeline on a payment proof or a
    complaint photo and returns the reason as a tool error the model may act
    on. This function makes the CONSEQUENCE independent of that acting: if the
    model called the vision tool on such an image at all, the conversation
    moves to a human no matter what the reply said.
    """
    for call in tool_calls or []:
        if call.get("name") != "find_product_by_image" or call.get("status") != "error":
            continue
        error = call.get("error") or ""
        prefix = "image requires handover: "
        if error.startswith(prefix):
            reason = error[len(prefix) :]
            if reason in _IMAGE_HANDOFF_REASONS:
                return reason
    return None


async def _shown_line(
    session: AsyncSession, tenant_id: uuid.UUID, shown_ids: list[str]
) -> str | None:
    """The numbered shown-items context, with TITLES.

    The referent resolver is gone — "التاني" is the model's call now, and it
    needs a numbered list it can count. Titles, not bare ids: a list of UUIDs
    is exactly the cryptic-identifier shape the tool-design research found
    degrades model precision. The id stays on each line so the model can call
    get_product_details / get_product_photos directly.
    """
    if not shown_ids:
        return None
    from app.modules.catalog.models import Product

    rows = (
        await session.execute(
            select(Product.id, Product.title).where(
                Product.tenant_id == tenant_id,
                Product.id.in_([uuid.UUID(str(pid)) for pid in shown_ids]),
            )
        )
    ).all()
    titles = {str(pid): title for pid, title in rows}
    numbered = "\n".join(
        f"{position}. {titles.get(pid, 'منتج غير معروف')} (id={pid})"
        for position, pid in enumerate(shown_ids, 1)
    )
    return "المنتجات اللي اعرضت على العميل بالترتيب:\n" + numbered


def _context_lines(
    turn: InboundTurn,
    shown_line: str | None,
    customer_name: str | None,
    customer_locale: str | None,
    channel: str | None,
    tenant_timezone: str | None,
    vision_results: list[MatchResult],
    skipped_photos: int,
    vision_failures: int = 0,
    audio_rides: bool = False,
    include_ambient: bool = True,
) -> str | None:
    """The system-owned context block, or None when there is nothing to say.

    System-generated facts only (state, vision, customer identity) — never
    customer text, which rides the user message where it belongs (§132
    untrusted zone). These lines are the model's EYES, not its instructions.
    """
    lines: list[str] = []
    if include_ambient:
        # Today, as a WEEKDAY with no digits: "بعد يومين" needs the model to
        # know what day it is, but a numeral here would be an ungrounded
        # numeral the moment the model repeats it — weekday names carry no
        # numbers, so the reply stays honest AND grounded. The ambient block
        # NEVER rescues an otherwise-empty turn: a blank message still
        # short-circuits without spending a model call.
        lines.append("النهارده " + _ARABIC_WEEKDAYS[_today_weekday(tenant_timezone)])
        if channel:
            lines.append(f"القناة: {channel}")
    if customer_name:
        line = f"اسم العميل: {customer_name}"
        if customer_locale:
            line += f" (لغة العميل: {customer_locale})"
        lines.append(line)
    if shown_line:
        lines.append(shown_line)
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
    if vision_failures:
        # OUR failure, not the customer's: say so honestly. Solving it is the
        # model's call — apologize, offer the photo again, or hand over.
        lines.append(
            "صورة العميل مقدرناش نحللها بسبب مشكلة في نظامنا — اعتذر واعرض "
            "يبعته تاني أو تحويله لموظف لو الصورة ضرورية، ومتحاولش تخمّن محتواها."
        )
    if turn.has_voice and not turn.voice_transcript and not audio_rides:
        # Only when the audio will NOT reach the model. On the direct-Omni
        # path the worker skips transcription on purpose and the bytes ride
        # the call — telling the model the voice "could not be transcribed"
        # while it hears the customer makes it distrust its own ears.
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
        if turn.voice_transcript:
            return turn.voice_transcript
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
    image_classifier: ImageClassifier | None = None,
) -> TurnOutcome:
    """One customer turn through the whole stack."""
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

    # Vision: first photo only (v1); URLs are minted by the caller, keys
    # without one are acknowledged as unprocessed rather than dropped.
    #
    # A vision FAILURE must degrade, never fail the ingest: the provider
    # raising (a misconfigured key, an outage) used to propagate out of the
    # turn and dead-letter a perfectly healthy message. Vision is a BONUS,
    # the same policy the knowledge context rides under: log loudly, tell
    # the model, keep going.
    vision_results: list[MatchResult] = []
    processed = 0
    vision_failures = 0
    classified_kind: ImageKind | None = None
    precomputed_match: MatchResult | None = None
    for key in turn.image_keys[:MAX_PHOTOS_PER_TURN]:
        url = params.image_urls.get(key)
        if not url:
            continue
        processed += 1
        if classified_kind is None:
            if image_classifier is not None:
                classified_kind = await image_classifier(session, params.tenant_id, url)
            else:
                from app.modules.ai.core.resolver import resolve_agent_by_kind_optional

                agent_row = await resolve_agent_by_kind_optional(
                    session, params.tenant_id, "customer"
                )
                alias = (
                    AgentRunner._alias_for(agent_row)
                    if agent_row is not None
                    else "fast"
                )
                gateway = getattr(_runner, "gateway", None)
                if gateway is None:
                    from app.modules.ai.gateway import AIGateway

                    gateway = AIGateway()
                classified_kind = await _default_classify_image_kind(
                    session, params.tenant_id, url, gateway=gateway, alias=alias
                )
        if classified_kind in _SENSITIVE_IMAGE_KINDS:
            # §12.5 enforced SERVER-SIDE, before any embedding/rerank egress:
            # a payment proof or complaint photo goes to a human, no matter
            # what the model would have proposed. No model call runs — the
            # fixed ack states receipt and handover without confirming money
            # details nobody has verified. (Parked: the image session owns
            # this path's redesign.)
            reason = (
                "payment_proof_requires_human"
                if classified_kind is ImageKind.PAYMENT_PROOF
                else "complaint_requires_human"
            )
            logger.info(
                "ai.image_handover_preclass storage_key=%s kind=%s",
                key,
                classified_kind.value,
            )
            return TurnOutcome(
                reply=_SENSITIVE_IMAGE_ACK,
                handover_reason="policy",
                handover_note=f"image:{reason}",
                vision=[
                    {
                        "confidence": "high",
                        "reason": f"classified_{classified_kind.value}_pre_egress",
                    }
                ],
                state_version=state_version,
            )
        if classified_kind is not ImageKind.PRODUCT:
            # Not a product photo: no retrieval egress; the model answers from
            # the image itself (which still rides the turn).
            continue
        try:
            # begin_nested: a SQL failure inside the vision pipeline (not just
            # a provider error) would otherwise leave the caller's transaction
            # aborted — the reply write and the state patch after it would die
            # too, and a healthy message would dead-letter. The savepoint
            # bounds the damage to the vision pass; the except below handles
            # whatever escapes it and the transaction stays usable.
            async with session.begin_nested():
                precomputed_match = await run_vision_match(
                    session,
                    params.tenant_id,
                    image_url=url,
                    text_hint=turn.text_hint(),
                )
                vision_results.append(precomputed_match)
        except Exception:  # noqa: BLE001 — a broken photo pipeline is not the customer's problem
            vision_failures += 1
            precomputed_match = None
            logger.warning(
                "ai.vision_failed storage_key=%s — the turn answers WITHOUT this photo",
                key,
                exc_info=True,
            )
    skipped_photos = len(turn.image_keys) - processed

    shown = list(state.shown_items) if state else []
    shown_line = await _shown_line(session, params.tenant_id, shown)
    has_content = bool(
        turn.text
        or turn.voice_transcript
        or turn.has_voice
        or turn.other_media
        or shown_line
        or vision_results
        or turn.image_keys
    )
    context = _context_lines(
        turn,
        shown_line,
        params.customer_name,
        params.customer_locale,
        params.channel,
        params.tenant_timezone,
        vision_results,
        skipped_photos,
        vision_failures,
        audio_rides=params.audio_rides,
        include_ambient=has_content,
    )
    user_message = _message_text(turn, bool(vision_results))
    if not user_message and not context:
        # Nothing actionable arrived (e.g. an empty body after stripping).
        return TurnOutcome(
            reply=None,
            state_version=state_version,
            blocked_reason="empty_turn",
        )

    # The hook's retrieved snippets and the system-owned context lines
    # (state, vision, customer identity) travel SEPARATELY: the runtime
    # labels each for what it is, and a knowledge failure cannot dress the
    # customer's name up as a retrieved snippet. Both stay OUTSIDE the
    # system prompt (§132).
    result: AgentRunResult = await _runner.run(
        session,
        params.tenant_id,
        agent_id=params.agent_id,
        conversation_id=params.conversation_id,
        inbound_message_id=params.inbound_message_id,
        user_message=user_message,
        customer_id=params.customer_id,
        knowledge_context=params.knowledge_context,
        context_lines=context,
        vision_state={
            "classified_kind": (
                classified_kind.value if classified_kind is not None else None
            ),
            "match": precomputed_match,
        },
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
            # No tool produced a fact, so grounding has nothing to compare
            # against. The financial-claim guardrail only recognises price /
            # stock / money wording, so a policy or schedule figure ("الاسترجاع
            # خلال 14 يوم", "بنقفل 10") used to pass here untouched. The
            # system prompt makes tools the only source of a number, so with
            # none behind the reply, a numeral is allowed only as an echo of
            # the customer's own message. Withholding hands the turn to a
            # human (silence beats an invented policy — decided 2026-10-18).
            grounding = "skipped_no_facts"
            # A tool that RAN and succeeded is a source even when it returned
            # no figure ("لقيت 0 نتيجة" after an empty search: the zero is the
            # tool's answer). Only a run with no successful tool at all has
            # nothing behind its numbers.
            any_tool_ok = any(c.get("status") == "ok" for c in result.tool_calls_made)
            reason = (
                None
                if any_tool_ok
                else check_unsourced_numerals(result.content, user_message)
            )
            if reason is not None:
                grounding = "failed"
                reply = None
                blocked_reason = f"grounding:{reason}"
        else:
            # No regeneration HERE (§8): the runner already owns the one
            # grounded regen. A reply that survived it does not need a second
            # deterministic bounce; the deadline only reports lateness.
            reason = check_grounding(result.content, facts)
            if reason is None:
                grounding = "ok"
            else:
                grounding = "failed"
                reply = None
                blocked_reason = f"grounding:{reason}"

    # State patch: what THIS run actually SHOWED, append-only. Vision-match
    # candidates are deliberately EXCLUDED — the runtime does not deliver
    # them to the customer until get_product_photos sends their images, and
    # the numbered shown list is the model's ground truth for "التاني": an
    # item the customer never saw must not occupy a position in it.
    # A stale version means a concurrent turn moved the row — the lists are
    # append-only and deduped, so re-applying against a fresh read is
    # idempotent.
    new_shown = list(result.shown_product_ids)
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

    # §12.5: the model PROPOSED an image kind and the classifier refused it —
    # a payment proof or a complaint photo is a human's job. Deterministic:
    # the conversation moves even if the model's own reply was vague.
    image_handoff = _image_handoff_reason(result.tool_calls_made)

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
        grounding=grounding,
        blocked_reason=blocked_reason,
        deadline_exceeded=deadline_exceeded,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        run_id=result.run_id,
        handover_reason="policy" if image_handoff else None,
        handover_note=f"image:{image_handoff}" if image_handoff else None,
    )
