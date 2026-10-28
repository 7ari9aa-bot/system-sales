"""The cases are an instrument too. Two properties are pinned here:

1. SENSITIVE: a lazy agent (says 'ok', does nothing) must FAIL every case. A case it passes
   proves nothing, because any broken agent would pass it too.
2. NOT TOO NARROW: a plainly correct reply must PASS. A case that rejects a good answer would
   fail good agents for the wrong reason and teach us to loosen the wrong thing.
"""

from __future__ import annotations

import pytest

from tests.agent_eval.cases_core import CASES as CORE
from tests.agent_eval.cases_failure_modes import CASES as MODES
from tests.agent_eval.cases_flows import CASES as FLOWS
from tests.agent_eval.graders import Observed, grade
from tests.agent_eval.reference_replies import GOOD

ALL = CORE + FLOWS + MODES


def _blocking(case, observed_per_turn):
    out = []
    for turn, observed in zip(case.turns, observed_per_turn, strict=True):
        out += [f for f in grade(turn.expect, observed) if f.blocking]
    return out


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in ALL]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", ALL, ids=[c.id for c in ALL])
def test_a_lazy_agent_fails_the_case(case) -> None:
    lazy = [Observed(reply="تمام") for _ in case.turns]
    assert _blocking(case, lazy), f"{case.id} passes a do-nothing agent: it proves nothing"


@pytest.mark.parametrize("case", ALL, ids=[c.id for c in ALL])
def test_a_plainly_good_reply_passes_the_case(case) -> None:
    assert case.id in GOOD, f"{case.id} has no reference reply"
    good = GOOD[case.id]
    assert len(good) == len(case.turns)
    findings = _blocking(case, good)
    assert not findings, [f"{f.check}: {f.detail}" for f in findings]
