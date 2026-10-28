"""Roll case results up into the one answer a release decision needs.

The headline is NOT an average pass rate. A suite can be 97% green and still contain the one
failure that must never ship (an invented policy). So the verdict is a gate:

- any failed ``critical`` case blocks the release, whatever the rest says;
- ``high`` failures are counted against a budget (default: at most 10% of high cases);
- ``normal`` failures are reported, never blocking.

The same report is produced for a scripted model and for a live one; only the caller differs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from tests.agent_eval.case_schema import Case
from tests.agent_eval.graders import CaseResult

HIGH_FAILURE_BUDGET = 0.10


@dataclass(frozen=True)
class Verdict:
    ship: bool
    reasons: tuple[str, ...]
    by_risk: dict[str, tuple[int, int]]  # risk -> (passed, total)
    by_category: dict[str, tuple[int, int]]
    failures: tuple[tuple[str, str, str], ...]  # (case id, risk, "check: detail; ...")


def summarise(cases: list[Case], results: list[CaseResult]) -> Verdict:
    by_id = {c.id: c for c in cases}
    risk: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    failures: list[tuple[str, str, str]] = []

    for r in results:
        case = by_id[r.case_id]
        for bucket in (risk[case.risk], cat[case.category]):
            bucket[1] += 1
            bucket[0] += 1 if r.passed else 0
        if not r.passed:
            why = "; ".join(f"{f.check}: {f.detail}" for f in r.findings if f.blocking)
            failures.append((r.case_id, case.risk, why))

    reasons: list[str] = []
    crit_failed = [f for f in failures if f[1] == "critical"]
    if crit_failed:
        reasons.append(
            f"{len(crit_failed)} critical case(s) failed: " + ", ".join(f[0] for f in crit_failed)
        )
    high_passed, high_total = risk["high"]
    if high_total and (high_total - high_passed) / high_total > HIGH_FAILURE_BUDGET:
        reasons.append(
            f"high-risk failures {high_total - high_passed}/{high_total} exceed the "
            f"{HIGH_FAILURE_BUDGET:.0%} budget"
        )
    missing = {c.id for c in cases} - {r.case_id for r in results}
    if missing:
        reasons.append(f"{len(missing)} case(s) were never run: {sorted(missing)[:3]}")

    return Verdict(
        ship=not reasons,
        reasons=tuple(reasons),
        by_risk={k: (v[0], v[1]) for k, v in risk.items()},
        by_category={k: (v[0], v[1]) for k, v in sorted(cat.items())},
        failures=tuple(failures),
    )


def render(v: Verdict) -> str:
    lines = ["SHIP" if v.ship else "DO NOT SHIP"]
    lines += [f"  - {r}" for r in v.reasons]
    lines.append("by risk:")
    for k in ("critical", "high", "normal"):
        if k in v.by_risk:
            p, t = v.by_risk[k]
            lines.append(f"  {k:<9}{p}/{t}")
    lines.append("by category:")
    lines += [f"  {k:<18}{p}/{t}" for k, (p, t) in v.by_category.items()]
    if v.failures:
        lines.append("failures:")
        lines += [f"  [{risk}] {cid}: {why}" for cid, risk, why in v.failures]
    return "\n".join(lines)
