"""Validators (spec §9.2, §10.3, §11) — nothing reaches the merchant unproven.

Two gates, both deterministic:

* ``validate_finding`` — the causality ladder: a claim may never be
  stronger than its evidence. TEMPORAL_ASSOCIATION evidence caps the
  relationship at TEMPORAL_ASSOCIATION; only CAUSAL evidence may say
  "caused". HYPOTHESIS findings must be phrased as uncertainty.

* ``validate_response`` — every placeholder resolves, no free numbers, no
  unrendered tokens. One regeneration is the caller's policy; this module
  only returns the PROBLEMS it found.
"""

from __future__ import annotations

import re

from app.modules.analytics.contracts import (
    AnswerDraft,
    Finding,
    Relationship,
)
from app.modules.analytics.numbers import free_numerals

#: Wording that asserts causation. Allowed ONLY when the finding's
#: relationship is CAUSAL (experiment or real causal method backed).
_CAUSAL_MARKERS = (" caused ", "سبب مباشر", "بسبب", " causally ")
#: Hedges that keep an association claim honest — any of these satisfies a
#: TEMPORAL_ASSOCIATION/CORRELATION finding's phrasing check.
_ASSOCIATION_HEDGES = (
    "coincided",
    "may have contributed",
    "يرجح",
    "قد يكون",
    "تزامن مع",
    "ساهم",
)
_HYPOTHESIS_HEDGES = ("احتمال", "يبدو", "فرضية", "possibly", "hypothesis")
_FREE_NUMBER_RE = re.compile(r"[0-9٠-٩][0-9٠-٩.,%]*")
_LINGUISTIC_ALLOWLIST = ("يومين", "موديلين", "أسبوعين", "شهرين", "أول")


def validate_finding(finding: Finding) -> list[str]:
    """Rejections for one finding; empty list means it may pass."""
    problems: list[str] = []
    text = f" {finding.statement} "
    # §9.2 ladder: the WORDING may never outrun the relationship. Text that
    # asserts cause with a non-CAUSAL relationship is rejected, whatever the
    # declared field says.
    asserts_cause = any(marker in text for marker in _CAUSAL_MARKERS)
    if asserts_cause and finding.relationship is not Relationship.CAUSAL:
        problems.append("causal wording requires CAUSAL evidence (experiment or causal method)")
    if finding.relationship in (
        Relationship.TEMPORAL_ASSOCIATION,
        Relationship.CORRELATION,
    ):
        if not any(hedge in text for hedge in _ASSOCIATION_HEDGES):
            problems.append("association findings must hedge (coincided / may have contributed)")
    if finding.type == "HYPOTHESIS" and not any(hedge in text for hedge in _HYPOTHESIS_HEDGES):
        problems.append("hypotheses must be phrased as hypotheses")
    if not finding.evidence_refs:
        problems.append("finding has no evidence")
    return problems


def validate_response(draft: AnswerDraft, rendered_text: str) -> list[str]:
    """§10.3 — the response gate. ``rendered_text`` is the draft's text
    AFTER the number renderer ran; problems mean REJECT (one regeneration,
    then the deterministic safe response — the caller owns that policy)."""
    problems: list[str] = []
    if re.search(r"\{\{[A-Za-z0-9_]+:[a-z_]+\}\}", rendered_text):
        problems.append("unrendered placeholder survived into the answer")
    for numeral in free_numerals(rendered_text, allowlist=_LINGUISTIC_ALLOWLIST):
        problems.append(f"free number in answer: {numeral}")
    for finding in draft.findings:
        if finding.confidence == "HIGH" and finding.type == "HYPOTHESIS":
            problems.append("a HYPOTHESIS finding reached HIGH confidence")
    return problems
