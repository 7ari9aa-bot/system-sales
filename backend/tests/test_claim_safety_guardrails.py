"""Tests for V12 Wave D §26: Commercial Claim Safety and Evidence Verification."""

from __future__ import annotations

import uuid

from app.core.guardrails import claim_checks, claims_facts, default_guardrail


def test_claims_facts_detection():
    # Price and currency assertions
    assert claims_facts("The price is 150 SAR")
    assert claims_facts("Total amount: 50 USD")
    assert claims_facts("السعر 100 ريال")
    assert claims_facts("متوفر 5 قطع في المخزن")
    assert claims_facts("Discount of 25%")

    # Non-factual conversational text
    assert not claims_facts("Hello, how can I help you today?")
    assert not claims_facts("We have a wide variety of shoes in our store.")
    assert not claims_facts("شكراً لتواصلك معنا")


def test_claim_checks_blocks_unverified_commercial_claims():
    content = "The price of this item is 250 SAR and we have 3 in stock."

    # No evidence provided -> BLOCK
    verdict = claim_checks(content, {})
    assert verdict is not None
    assert verdict.decision == "block"
    assert verdict.reason == "unverified_commercial_claim"


def test_claim_checks_allows_when_evidence_is_present():
    content = "The price of this item is 250 SAR and we have 3 in stock."

    # 1. With evidence_set_id
    verdict_set = claim_checks(content, {"evidence_set_id": uuid.uuid4()})
    assert verdict_set is None

    # 2. With verified_facts
    verdict_facts = claim_checks(content, {"verified_facts": [{"price": 250}]})
    assert verdict_facts is None

    # 3. With tool_results
    verdict_tools = claim_checks(content, {"tool_results": [{"price": 250}]})
    assert verdict_tools is None


def test_claim_checks_allows_non_commercial_claims_without_evidence():
    content = "Our return policy allows returns within 14 days of purchase."
    # Not asserting specific prices or stock quantities
    verdict = claim_checks(content, {})
    assert verdict is None


def test_default_guardrail_with_claim_check_enabled():
    guardrail = default_guardrail(require_claim_check=True)

    unverified = "The total cost will be 500 SAR."
    res_blocked = guardrail.evaluate(unverified, {})
    assert res_blocked.decision == "block"
    assert res_blocked.reason == "unverified_commercial_claim"
    assert "claim_checks" in res_blocked.checks

    # With evidence
    res_allowed = guardrail.evaluate(unverified, {"evidence_set_id": uuid.uuid4()})
    assert res_allowed.decision == "allow"
