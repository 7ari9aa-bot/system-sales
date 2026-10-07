"""The risk engine: closed registry, one-way escalation, ADR-060's approval
mapping — each a security property, each proven here."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.risk import (
    MONEY_ESCALATION_THRESHOLD,
    ActorType,
    RiskContext,
    RiskLevel,
    classify,
    known_actions,
)

BASE_LEVELS = {
    "search_products": RiskLevel.LOW,
    "get_customer": RiskLevel.LOW,
    "add_task": RiskLevel.MEDIUM,
    "send_message": RiskLevel.MEDIUM,
    "create_order": RiskLevel.HIGH,
    "cancel_order": RiskLevel.HIGH,
    "capture_payment": RiskLevel.CRITICAL,
    "refund": RiskLevel.CRITICAL,
    "merge_identity": RiskLevel.CRITICAL,
}


@pytest.mark.parametrize("action,expected", sorted(BASE_LEVELS.items()))
def test_registry_actions_classify_at_their_base_level(action, expected):
    assessment = classify(action, RiskContext(actor_type=ActorType.SYSTEM))

    assert assessment.level is expected
    assert assessment.base_level is expected
    assert assessment.escalations == ()


# The SHIPPED registry, frozen at MODULE IMPORT (collection). The snapshot
# must live here, outside any test body: approval tests register fixture
# tools (purge_customer_data) into the module-global TOOLS and unregister
# nothing, so a snapshot taken inside a test body runs AFTER their pollution
# and sees an action that exists nowhere in the app.
_SHIPPED_TOOLS = frozenset(__import__("app.modules.ai.tools", fromlist=["TOOLS"]).TOOLS)


def test_registry_covers_every_ai_tool_without_disagreement():
    from app.modules.ai import tools as ai_tools

    for name in sorted(_SHIPPED_TOOLS):
        spec = ai_tools.TOOLS[name]
        assert name in known_actions(), f"AI tool {name} is missing from the risk registry"
        spec_level = RiskLevel[spec.risk_level.upper()]
        assert classify(name).level is spec_level, (
            f"AI registry says {name} is {spec.risk_level}, risk engine disagrees"
        )


def test_an_unknown_action_fails_toward_caution():
    assessment = classify("totally_novel_action")

    assert assessment.level is RiskLevel.HIGH
    assert assessment.unknown_action is True
    assert "unknown action" in assessment.escalations[0]


def test_a_large_amount_escalates_one_level():
    small = classify("create_order", RiskContext(amount=Decimal("100")))
    large = classify("create_order", RiskContext(amount=MONEY_ESCALATION_THRESHOLD * 2))

    assert small.level is RiskLevel.HIGH
    assert large.level is RiskLevel.CRITICAL
    assert any("amount" in e for e in large.escalations)


def test_escalation_never_exceeds_critical():
    assessment = classify("capture_payment", RiskContext(amount=MONEY_ESCALATION_THRESHOLD * 10))

    assert assessment.level is RiskLevel.CRITICAL


def test_data_sensitivity_escalates():
    assessment = classify("get_customer", RiskContext(data_sensitivity=True))

    assert assessment.level is RiskLevel.MEDIUM
    assert "sensitive data" in assessment.escalations[0]


def test_tenant_floor_raises_but_never_lowers():
    raised = classify("add_task", RiskContext(tenant_policy_floor=RiskLevel.HIGH))
    lowered = classify("capture_payment", RiskContext(tenant_policy_floor=RiskLevel.LOW))

    assert raised.level is RiskLevel.HIGH
    assert "tenant policy floor" in raised.escalations
    assert lowered.level is RiskLevel.CRITICAL, "a floor cannot soften a critical action"


def test_float_amounts_are_refused_like_every_money_boundary():
    with pytest.raises(TypeError, match="Decimal"):
        classify("create_order", RiskContext(amount=100.0))


def test_durable_approval_mapping_per_adr_060():
    assessment = classify("add_tag")  # MEDIUM

    assert assessment.requires_durable_approval(ActorType.HUMAN) is False
    assert assessment.requires_durable_approval(ActorType.AI_AGENT) is True
    assert assessment.requires_durable_approval(ActorType.AUTOMATION) is True

    critical = classify("capture_payment")

    assert critical.requires_durable_approval(ActorType.HUMAN) is True
    assert critical.requires_durable_approval(ActorType.SYSTEM) is True


def test_low_risk_actions_take_the_fast_path_for_every_actor():
    low = classify("search_products")

    for actor in ActorType:
        assert low.requires_durable_approval(actor) is False
