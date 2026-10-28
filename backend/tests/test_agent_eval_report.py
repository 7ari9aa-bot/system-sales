"""The release gate decides ship / do-not-ship, so its own logic is pinned."""

from __future__ import annotations

from tests.agent_eval.case_schema import Case, StoreFixture, Turn
from tests.agent_eval.graders import CaseResult, Finding
from tests.agent_eval.report import render, summarise


def _case(cid: str, risk: str, category: str = "product_info") -> Case:
    return Case(
        id=cid, category=category, risk=risk, title=cid, store=StoreFixture(), turns=(Turn("x"),)
    )


def _ok(cid: str, risk: str) -> CaseResult:
    return CaseResult(case_id=cid, risk=risk)


def _bad(cid: str, risk: str) -> CaseResult:
    return CaseResult(case_id=cid, risk=risk, findings=[Finding("forbidden", "bad")])


def test_one_critical_failure_blocks_even_when_everything_else_passes() -> None:
    cases = [_case("c1", "critical")] + [_case(f"h{i}", "high") for i in range(20)]
    results = [_bad("c1", "critical")] + [_ok(f"h{i}", "high") for i in range(20)]
    verdict = summarise(cases, results)
    assert not verdict.ship
    assert "critical" in verdict.reasons[0]


def test_all_green_ships() -> None:
    cases = [_case("c1", "critical"), _case("h1", "high"), _case("n1", "normal")]
    verdict = summarise(cases, [_ok(c.id, c.risk) for c in cases])
    assert verdict.ship and verdict.reasons == ()


def test_high_failures_within_budget_do_not_block() -> None:
    cases = [_case(f"h{i}", "high") for i in range(20)]
    results = [_bad("h0", "high"), _bad("h1", "high")] + [
        _ok(f"h{i}", "high") for i in range(2, 20)
    ]
    assert summarise(cases, results).ship  # exactly 10%


def test_high_failures_over_budget_block() -> None:
    cases = [_case(f"h{i}", "high") for i in range(20)]
    results = [_bad(f"h{i}", "high") for i in range(3)] + [
        _ok(f"h{i}", "high") for i in range(3, 20)
    ]
    assert not summarise(cases, results).ship  # 15%


def test_normal_failures_never_block() -> None:
    cases = [_case("c1", "critical"), _case("n1", "normal")]
    assert summarise(cases, [_ok("c1", "critical"), _bad("n1", "normal")]).ship


def test_a_case_that_never_ran_blocks_instead_of_counting_as_a_pass() -> None:
    cases = [_case("c1", "critical"), _case("c2", "critical")]
    verdict = summarise(cases, [_ok("c1", "critical")])
    assert not verdict.ship
    assert "never run" in " ".join(verdict.reasons)


def test_an_advisory_only_finding_does_not_fail_the_case() -> None:
    soft = CaseResult(
        case_id="n1", risk="normal", findings=[Finding("length", "long", blocking=False)]
    )
    assert soft.passed


def test_the_rendered_report_names_every_failure() -> None:
    cases = [_case("c1", "critical", "adversarial")]
    text = render(summarise(cases, [_bad("c1", "critical")]))
    assert text.startswith("DO NOT SHIP")
    assert "c1" in text and "adversarial" in text
