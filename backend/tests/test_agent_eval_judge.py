"""The judge is tested with scripted models: no key, no network, no money.

The point is not that a real model judges well (only a live run can say that) but that the
machinery around it cannot quietly approve things.
"""

from __future__ import annotations

import pytest

from tests.agent_eval import judge
from tests.agent_eval.judge import (
    CALIBRATION,
    GENERIC_CRITERIA,
    SHOP,
    calibrate,
    judge_reply,
)


def _always(text: str):
    async def chat(_system: str, _user: str) -> str:
        return text

    return chat


YES = '{"verdict": "yes", "reason": "ok"}'
NO = '{"verdict": "no", "reason": "bad"}'


async def _run(chat, rubric=()):
    return await judge_reply(chat, shop_data=SHOP, customer="L؟", reply="أيوه", rubric=rubric)


# ---- it fails closed: nothing ambiguous may count as a pass ---------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "yes",
        "sure, looks good",
        "{not json}",
        '{"verdict": "maybe"}',
        '{"verdict": ""}',
        '{"reason": "no verdict key"}',
        "[]",
    ],
)
async def test_an_unclear_answer_is_a_failure_not_a_pass(raw) -> None:
    verdicts = await _run(_always(raw))
    assert verdicts and not any(v.passed for v in verdicts)


async def test_a_judge_call_that_raises_is_a_failure_not_a_pass() -> None:
    async def boom(_s: str, _u: str) -> str:
        raise TimeoutError

    verdicts = await _run(boom)
    assert not any(v.passed for v in verdicts)
    assert "TimeoutError" in verdicts[0].reason


async def test_a_clear_yes_passes_and_a_clear_no_fails() -> None:
    assert all(v.passed for v in await _run(_always(YES)))
    assert not any(v.passed for v in await _run(_always(NO)))


async def test_json_wrapped_in_chatter_is_still_read() -> None:
    verdicts = await _run(_always(f"Here is my answer: {YES} thanks"))
    assert all(v.passed for v in verdicts)


# ---- structure ------------------------------------------------------------------------------
async def test_every_criterion_is_asked_on_its_own() -> None:
    seen: list[str] = []

    async def spy(_system: str, user: str) -> str:
        seen.append(user)
        return YES

    verdicts = await _run(spy, rubric=("Does it avoid promising a refund?", "Is it polite?"))

    assert len(seen) == len(GENERIC_CRITERIA) + 2 == len(verdicts)
    assert [v.criterion for v in verdicts][-2:] == ["rubric-1", "rubric-2"]
    # each call carries exactly one criterion: answers cannot contaminate each other
    assert sum("Is it polite?" in u for u in seen) == 1


async def test_the_judge_is_shown_the_shop_data_it_must_ground_against() -> None:
    seen: list[str] = []

    async def spy(_system: str, user: str) -> str:
        seen.append(user)
        return YES

    await _run(spy)
    assert all("تيشيرت قطن" in u for u in seen)


# ---- calibration: a lazy or contrary judge must be exposed ----------------------------------
def _scripted_correctly():
    """A model that answers the calibration set the way a careful human would."""
    expected = {(c[2]): c[3] for c in CALIBRATION}

    async def chat(_system: str, user: str) -> str:
        for reply, ok in expected.items():
            if f"AGENT REPLY:\n{reply}\n" in user:
                return YES if ok else NO
        return NO

    return chat


async def test_a_correct_judge_passes_calibration() -> None:
    assert await calibrate(_scripted_correctly()) == []


async def test_a_judge_that_approves_everything_is_caught_by_calibration() -> None:
    wrong = await calibrate(_always(YES))
    assert wrong, "an approve-everything judge must not pass calibration"
    assert len(wrong) == sum(1 for c in CALIBRATION if not c[3])


async def test_a_judge_that_rejects_everything_is_caught_by_calibration() -> None:
    wrong = await calibrate(_always(NO))
    assert len(wrong) == sum(1 for c in CALIBRATION if c[3])


async def test_a_judge_that_returns_garbage_is_caught_by_calibration() -> None:
    assert len(await calibrate(_always("I think it is fine"))) == sum(
        1 for c in CALIBRATION if c[3]
    )


def test_calibration_has_both_kinds_of_answer_for_each_generic_criterion() -> None:
    for name, _ in GENERIC_CRITERIA:
        verdicts = {c[3] for c in CALIBRATION if c[0] == name}
        assert verdicts == {True, False}, f"{name} needs a known-good AND a known-bad example"


def test_the_module_exposes_no_hidden_pass_path() -> None:
    assert not hasattr(judge, "DEFAULT_PASS")


# ---- the cap, the trust gate, and judging a whole case --------------------------------------
async def test_the_call_cap_is_never_exceeded() -> None:
    from tests.agent_eval.judge import JudgeBudgetExceeded, capped

    calls = 0

    async def chat(_s: str, _u: str) -> str:
        nonlocal calls
        calls += 1
        return YES

    limited, used = capped(chat, 3)
    for _ in range(3):
        await limited("s", "u")
    with pytest.raises(JudgeBudgetExceeded):
        await limited("s", "u")
    assert calls == 3 == used()


async def test_hitting_the_cap_mid_case_is_a_failure_not_a_pass() -> None:
    from tests.agent_eval.judge import capped

    limited, _ = capped(_always(YES), 1)
    verdicts = await _run(limited)  # needs 2 generic criteria; the second call is over the cap
    assert [v.passed for v in verdicts] == [True, False]
    assert "JudgeBudgetExceeded" in verdicts[1].reason


async def test_an_untrustworthy_judge_is_refused_before_any_verdict_is_used() -> None:
    from tests.agent_eval.judge import JudgeNotTrustworthy, require_calibrated

    with pytest.raises(JudgeNotTrustworthy):
        await require_calibrated(_always(YES))
    await require_calibrated(_scripted_correctly())  # a sound one passes silently


async def test_a_whole_case_is_judged_turn_by_turn_with_the_rubric_on_the_last() -> None:
    from types import SimpleNamespace

    from tests.agent_eval.judge import judge_case

    def rec(reply: str, grounding: str):
        return SimpleNamespace(
            customer="q", grounding=grounding, observed=SimpleNamespace(reply=reply)
        )

    case = SimpleNamespace(rubric=("no refund promised?",))
    seen: list[str] = []

    async def spy(_s: str, user: str) -> str:
        seen.append(user)
        return YES

    verdicts = await judge_case(spy, case, [rec("a", "G1"), rec("b", "G2")])

    names = [v.criterion for v in verdicts]
    assert names == [
        "turn1:natural",
        "turn1:grounded",
        "turn2:natural",
        "turn2:grounded",
        "turn2:rubric-1",
    ]
    # each turn is judged against what the agent read in THAT turn
    assert "G1" in seen[0] and "G2" in seen[2]
    assert sum("no refund promised?" in u for u in seen) == 1
