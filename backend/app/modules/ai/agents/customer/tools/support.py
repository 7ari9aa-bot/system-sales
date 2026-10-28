"""Support tools: find_support_playbook (the store's written solutions) and handover_to_human.

Split out of the former single-file ``customer/tools.py``; the code is unchanged.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.core.sql import LIKE_ESCAPE, like_pattern
from app.modules.ai.agents.customer.tools._shared import _parse_bound_id, _StrictArgs


class FindSupportPlaybookArgs(_StrictArgs):
    """The customer's problem in their own words."""

    problem: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=3, ge=1, le=5)


def _fold_arabic(text_: str) -> str:
    """Fold the spellings Egyptian customers vary freely, on BOTH sides.

    Hamza forms (أ إ آ) -> ا, ى -> ي, ة -> ه, and diacritics dropped, so
    "اتأخر" / "اتاخر" and "مقاس" / "مقاس" compare equal. Applied to the
    customer's words here and to the stored text in SQL (``_FOLD_SQL``), so the
    two sides always agree.
    """
    table = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
    return "".join(ch for ch in text_.translate(table) if not ("\u064b" <= ch <= "\u0652"))


def _fold_sql(column):
    """SQL twin of ``_fold_arabic`` for a text column."""
    folded = func.translate(column, "أإآىة", "اااية")
    return func.regexp_replace(folded, "[\u064b-\u0652]", "", "g")


# Function words carry no topic. Matched as substrings they hit inside other
# words ("في" inside "فين", "علي" inside "عليا"), so a question that shares
# nothing with a playbook still "matched" it. Folded spellings, like the text.
_PLAYBOOK_STOPWORDS = frozenset(
    _fold_arabic(w)
    for w in (
        # particles and pronouns
        "في فى من علي على الي الى عن مع ده دي دا هو هي انا انت احنا يا ما لا ان "
        "ليا ليك لي لك عليا عليه عليها معايا معاه ليه بتاعي بتاعتي بتاع "
        # question and request words
        "ايه ازاي امتي امتى فين هل ممكن عايز عايزه عاوز عاوزه اعرف اعرفه "
        # fillers, politeness, tense markers
        "لو لما مش كل بس كده اوي قوي جدا اهلا شكرا تمام عندكم عندي اللي "
        "لسه دلوقتي بقي بقى حاولت جربت"
    ).split()
)


# Words that describe THAT something is wrong, not WHAT. They appear in every
# kind of complaint ("المقاس غلط", "الفاتورة غلط", "الدفع غلط"), so matching on
# one alone sends a customer to the wrong fix. They still count toward a match
# when a topic word agrees; they just cannot be the only evidence.
_PLAYBOOK_GENERIC = frozenset(
    _fold_arabic(w)
    for w in {
        "غلط",
        "غلطه",
        "غلطات",
        "مشكله",
        "مشاكل",
        "عطل",
        "خربان",
        "بايظ",
        "مش",
        "شغال",
        "حاجه",
        "حاجات",
        "موضوع",
        "وحش",
        "سيء",
        "كويس",
        "تاني",
        "تانيه",
        "جديد",
    }
)


def _strip_clitic(word: str) -> str:
    """Drop a conjunction/preposition glued to the front of a word.

    Egyptian writing glues them on ("والمقاس", "بالفيزا", "وفشلت"), so the bare
    word never matches the stored one. Deliberately CONSERVATIVE: a lone ل / ب /
    ف is usually part of the word ("لبست", "بتفتحوا", "فتحوا"), and cutting it
    turns a verb into a different word. So only the unambiguous forms go: the
    definite-article compounds (وال / بال / فال / كال / لل) and a leading و,
    and only when a real stem of 3+ letters remains.
    """
    for prefix in ("وبال", "وال", "بال", "فال", "كال", "لل", "و"):
        if word.startswith(prefix) and len(word) - len(prefix) >= 3:
            return word[len(prefix) :]
    return word


def _playbook_word_arms(word: str) -> list[str]:
    """Match forms for one (already folded) customer word.

    The raw word; without a leading definite article ("الطلب" -> "طلب");
    without a trailing possessive/plural ("طلبي" / "طلبات" -> "طلب"); and both
    together. A stem under three letters is dropped: "%او%" would match half
    the language.
    """
    forms = {word}
    if word.startswith("ال") and len(word) > 4:
        forms.add(word[2:])
    for form in list(forms):
        for suffix in ("ي", "ك", "ه", "ها", "هم", "نا", "ات", "ين", "ون"):
            if form.endswith(suffix) and len(form) - len(suffix) >= 3:
                forms.add(form[: -len(suffix)])
    return [f for f in dict.fromkeys(forms) if len(f) >= 3 or f == word]


async def _find_support_playbook(
    session: AsyncSession, tenant_id: uuid.UUID, *, problem: str, limit: int = 3
) -> dict:
    """Recurring problems the merchant wrote a solution for, best match first.

    Deterministic: no embedding model, so a vendor outage cannot take support
    answers down. OR across the customer's words (colloquial Arabic rarely
    repeats the merchant's exact phrasing), ranked by how many words matched.
    The agent EXPLAINS the steps in its own words; nothing here executes.
    ``matched`` is explicit so "no playbook" is a stated fact the model hands
    over on, never a guess it fills in.
    """
    from app.modules.ai.models import SupportPlaybook

    # Stopword test on BOTH forms: "واعرف" is the stopword "اعرف" wearing a
    # clitic, and "حاولت" must not survive because stripping changed nothing.
    words = list(
        dict.fromkeys(
            stem
            for raw in _fold_arabic(problem).split()
            if raw and raw not in _PLAYBOOK_STOPWORDS
            for stem in (_strip_clitic(raw),)
            if stem not in _PLAYBOOK_STOPWORDS
        )
    )[:8]
    if not words:
        return {"matched": 0, "playbooks": []}
    title_f = _fold_sql(SupportPlaybook.title)
    problem_f = _fold_sql(SupportPlaybook.problem)
    per_word = []
    for word in words:
        ts_query = func.plainto_tsquery(literal_column("'simple'"), word)
        arms = [SupportPlaybook.search_ts.op("@@")(ts_query)]
        for pattern in _playbook_word_arms(word):
            arms += [
                title_f.ilike(like_pattern(pattern), escape=LIKE_ESCAPE),
                problem_f.ilike(like_pattern(pattern), escape=LIKE_ESCAPE),
            ]
        per_word.append(or_(*arms))

    hits = sum(case((expr, 1), else_=0) for expr in per_word)
    topic = [e for w, e in zip(words, per_word, strict=True) if w not in _PLAYBOOK_GENERIC]
    if not topic:
        # Only generic complaint words ("غلط", "مشكلة"): nothing says WHAT is
        # wrong, so no playbook can be the right one. Hand over, do not guess.
        return {"matched": 0, "playbooks": []}
    topic_hits = sum(case((expr, 1), else_=0) for expr in topic)
    # A topic word must agree AND at least half of ALL content words must match:
    # one shared word out of three is a coincidence, not an answer.
    min_hits = max(1, (len(words) + 1) // 2)
    rows = (
        await session.execute(
            select(
                SupportPlaybook.title,
                SupportPlaybook.problem,
                SupportPlaybook.steps,
                SupportPlaybook.escalate_when,
                hits.label("hits"),
            )
            .where(
                SupportPlaybook.tenant_id == tenant_id,
                SupportPlaybook.is_active.is_(True),
                topic_hits >= 1,
                hits >= min_hits,
            )
            .order_by(hits.desc(), SupportPlaybook.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return {
        "matched": len(rows),
        "playbooks": [
            {
                "title": title,
                "problem": prob,
                "steps": list(steps or []),
                "escalate_when": escalate_when,
            }
            for title, prob, steps, escalate_when, _hits in rows
        ],
    }


class HandoverToHumanArgs(BaseModel):
    # NOT _StrictArgs, on purpose. Models habitually add `conversation_id` /
    # `customer_id` from context; the scope is bound server-side and an extra
    # one is DROPPED before the handler (§132). Rejecting the call over a
    # harmless extra field would fail the escalation itself, and escalation is
    # the safety net for a problem the agent could not solve.
    #
    # There is deliberately no "purchase_intent" reason: a customer who wants
    # to buy, or who only asks a question, is served by the agent itself. A
    # handover needs an unsolved problem or an explicit request for a person.
    reason: Literal["complex_problem", "missing_data", "customer_request", "complaint"]
    summary: str = Field(min_length=1, max_length=1000)


async def _handover_to_human(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    reason: str,
    summary: str,
    context: dict | None = None,
) -> dict:
    """The MODEL's escalation decision, executed server-side.

    The conversation id comes from the server-bound context, never from the
    model. The write goes through the one handover writer (row + conversation
    status + outbox event + notification, idempotent), so a model that calls
    this twice, or a retried run, converges on one open handover. The summary
    is the model's own account — what it tried and what is missing — which is
    exactly what the staff member opening the conversation needs.
    """
    conversation_id = _parse_bound_id((context or {}).get("conversation_id"))
    if conversation_id is None:
        raise DomainError("no conversation bound to this tool call")

    from app.modules.ai.handover import request_human_takeover

    await request_human_takeover(
        session,
        tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        note=summary,
    )
    # Data only — NO instructions here. Trained models treat instructions in
    # tool results with skepticism and may ignore them (Anthropic's untrusted-
    # content guidance); the farewell behavior lives in the system prompt.
    return {
        "status": "handover_recorded",
        "reason": reason,
    }
