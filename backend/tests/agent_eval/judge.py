"""Model-graded quality checks: the part of "good" that code cannot decide.

Code (graders.py) decides what is checkable by rule: numbers, tools, forbidden phrases,
hand-over. This module covers what remains, which the standing instructions name explicitly:
a reply that reads like a person wrote it for THIS customer (not a canned template), that
claims nothing the shop data does not support, and the per-case ``rubric`` questions.

Two properties matter more than the prompt wording:

* It takes the chat function as a parameter, so the judge itself is tested with a scripted
  model and no key. A judge that has never been shown a known-bad reply is not evidence of
  anything; ``calibration`` below is the set it must get right before its verdicts are used.
* It fails closed. An unparseable or missing answer is a FAILED criterion, never a pass,
  because a judge that quietly approves everything is worse than no judge.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# (system, user) -> raw model text. The live runner binds this to the governed gateway.
ChatFn = Callable[[str, str], Awaitable[str]]

GENERIC_CRITERIA: tuple[tuple[str, str], ...] = (
    (
        "natural",
        "Does the reply read like a person answering THIS customer's actual message, in a "
        "similar register (Egyptian dialect if they used it)? Answer NO if it reads as a "
        "canned template: a fixed greeting block, a numbered boilerplate script, or wording "
        "that would be identical for any customer.",
    ),
    (
        "grounded",
        "Is every factual claim in the reply (prices, stock, policy, hours, delivery, "
        "invoice contents) supported by the SHOP DATA given below? Answer NO if it states "
        "anything the data does not contain, even if it sounds plausible.",
    ),
)

_SYSTEM = (
    "You are a strict reviewer of a shop's customer-service replies. You will be given the "
    "shop's data, the customer's message and the agent's reply, then one yes/no criterion. "
    "Judge ONLY the criterion. Do not be generous: when unsure, answer NO. "
    'Reply with JSON only: {"verdict": "yes" or "no", "reason": "<one short sentence>"}.'
)


@dataclass(frozen=True)
class Verdict:
    criterion: str
    passed: bool
    reason: str


def _parse(raw: str | None) -> tuple[bool, str]:
    """Fail closed: anything that is not a clear 'yes' is a failure."""
    if not raw:
        return False, "judge returned nothing"
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return False, f"judge answer was not JSON: {raw[:60]!r}"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False, f"judge answer was not valid JSON: {raw[:60]!r}"
    verdict = str(data.get("verdict", "")).strip().lower()
    reason = str(data.get("reason", "")).strip()[:200]
    if verdict == "yes":
        return True, reason
    if verdict == "no":
        return False, reason
    return False, f"judge verdict was neither yes nor no: {verdict!r}"


def _prompt(shop_data: str, customer: str, reply: str, criterion: str) -> str:
    return (
        f"SHOP DATA:\n{shop_data or '(nothing is written)'}\n\n"
        f"CUSTOMER MESSAGE:\n{customer}\n\n"
        f"AGENT REPLY:\n{reply}\n\n"
        f"CRITERION:\n{criterion}"
    )


async def judge_reply(
    chat: ChatFn,
    *,
    shop_data: str,
    customer: str,
    reply: str,
    rubric: tuple[str, ...] = (),
) -> list[Verdict]:
    """Ask each criterion separately (one judgement per call keeps answers uncontaminated)."""
    criteria = [*GENERIC_CRITERIA, *((f"rubric-{i + 1}", text) for i, text in enumerate(rubric))]
    out: list[Verdict] = []
    for name, text in criteria:
        try:
            raw = await chat(_SYSTEM, _prompt(shop_data, customer, reply, text))
        except Exception as exc:  # a failing judge call is a failed criterion, not a pass
            out.append(Verdict(name, False, f"judge call failed: {type(exc).__name__}"))
            continue
        passed, reason = _parse(raw)
        out.append(Verdict(name, passed, reason))
    return out


# --- calibration -----------------------------------------------------------------------------
# Replies whose correct verdict is known in advance. Before trusting the judge on a live run,
# it must get every one of these right; otherwise its verdicts mean nothing.
SHOP = "تيشيرت قطن: M بـ 250 جنيه (5 متاح)، L بـ 250 جنيه (3 متاح)، XL بـ 300 جنيه (0 متاح)."

CALIBRATION: tuple[tuple[str, str, str, bool], ...] = (
    # (criterion name, customer message, reply, the verdict a correct judge must give)
    ("grounded", "المقاس L موجود؟", "أيوه مقاس L متاح بـ 250 جنيه.", True),
    ("grounded", "المقاس L موجود؟", "أيوه متاح وعليه خصم 20% النهارده.", False),
    ("grounded", "بتفتحوا امتى؟", "بنفتح من 9 الصبح لـ 5 العصر.", False),
    ("grounded", "XL موجود؟", "أيوه XL متاح بـ 300 جنيه.", False),
    (
        "natural",
        "ازيك، المقاس L موجود؟",
        "أهلًا بيك! أيوه L متاح بـ 250 جنيه، تحب أجهزهولك؟",
        True,
    ),
    (
        "natural",
        "ازيك، المقاس L موجود؟",
        "عزيزي العميل، نشكرك على تواصلك معنا. يسعدنا خدمتك. لمزيد من المعلومات يرجى "
        "التواصل مع خدمة العملاء. شكرًا لاختيارك لنا.",
        False,
    ),
)


async def calibrate(chat: ChatFn) -> list[str]:
    """Return the calibration cases the judge got WRONG (empty list = safe to use)."""
    wrong: list[str] = []
    generic = dict(GENERIC_CRITERIA)
    for name, customer, reply, expected in CALIBRATION:
        verdicts = await judge_reply_single(chat, name, generic[name], customer, reply)
        if verdicts != expected:
            wrong.append(f"{name}: expected {expected} for {reply[:40]!r}")
    return wrong


async def judge_reply_single(
    chat: ChatFn, name: str, criterion: str, customer: str, reply: str
) -> bool:
    try:
        raw = await chat(_SYSTEM, _prompt(SHOP, customer, reply, criterion))
    except Exception:
        return False
    return _parse(raw)[0]


# --- running the judge over a finished case --------------------------------------------------
class JudgeBudgetExceeded(RuntimeError):
    """The live run asked the judge for more calls than the cap allows."""


class JudgeNotTrustworthy(RuntimeError):
    """The judge failed calibration, so none of its verdicts may be used."""


def capped(chat: ChatFn, max_calls: int) -> tuple[ChatFn, Callable[[], int]]:
    """Wrap ``chat`` so it can never be called more than ``max_calls`` times.

    A live evaluation multiplies quickly (cases x turns x criteria) and a stuck loop would
    keep paying. The cap is checked BEFORE each call, so the limit is never exceeded.
    """
    used = 0

    async def limited(system: str, user: str) -> str:
        nonlocal used
        if used >= max_calls:
            raise JudgeBudgetExceeded(f"judge call cap of {max_calls} reached")
        used += 1
        return await chat(system, user)

    return limited, lambda: used


async def require_calibrated(chat: ChatFn) -> None:
    """Refuse to continue unless the judge gets every known-answer case right."""
    wrong = await calibrate(chat)
    if wrong:
        raise JudgeNotTrustworthy("judge failed calibration: " + "; ".join(wrong))


async def judge_case(chat: ChatFn, case, records) -> list[Verdict]:
    """Judge every turn of a finished case. ``records`` are the runner's TurnRecords.

    Each reply is judged against what the agent actually READ (the tool results the runner
    captured), not against a description of the shop, so a claim is only 'grounded' if the
    agent could have known it. The case rubric applies to the final turn, where the outcome
    of the conversation is decided.
    """
    verdicts: list[Verdict] = []
    last = len(records) - 1
    for i, record in enumerate(records):
        for v in await judge_reply(
            chat,
            shop_data=record.grounding,
            customer=record.customer,
            reply=record.observed.reply,
            rubric=case.rubric if i == last else (),
        ):
            verdicts.append(Verdict(f"turn{i + 1}:{v.criterion}", v.passed, v.reason))
    return verdicts
