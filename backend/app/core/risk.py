"""The risk engine (V12 §16) — an LLM-free classifier that decides how much
governance an action must pass through.

Two rules make this a security boundary rather than a label:

1. The registry is CLOSED and code-reviewed. An action not in it classifies
   HIGH with an "unknown action" reason — availability over strictness, and
   always toward caution (V12's failure rule: when uncertain, fail closed).
2. Escalation is one-way. Amount thresholds, data sensitivity and a tenant's
   own policy floor can RAISE a level, never lower it.

ADR-060 decided the enforcement mapping (``requires_durable_approval``): the
Decision → Capability → Authority chain covers human actors too, risk-tiered —
a LOW/MEDIUM human action mints server-side inside the transaction (no extra
click), while HIGH/CRITICAL for humans and MEDIUM+ for AI agents and
automation take the durable §135 approval before anything executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class RiskLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    def __ge__(self, other: RiskLevel) -> bool:
        return self.value >= other.value

    def __gt__(self, other: RiskLevel) -> bool:
        return self.value > other.value


class ActorType(str, Enum):  # noqa: UP042 — str+Enum keeps .value comparisons string-safe
    """§133's actor vocabulary — the AI is a governed actor, not a human."""

    HUMAN = "human"
    AI_AGENT = "ai_agent"
    AUTOMATION = "automation"
    SYSTEM = "system"
    INTEGRATION = "integration"


#: Amount above which a money-moving action escalates one level. Deliberately
#: a small, stated number: it exists to catch "approved a sample order, spent
#: a warehouse" escalation, not to be a per-tenant pricing rule (§144's
#: budgets and the tenant's own policy floor own that).
MONEY_ESCALATION_THRESHOLD = Decimal("5000")


@dataclass(frozen=True)
class RiskContext:
    actor_type: ActorType = ActorType.HUMAN
    amount: Decimal | None = None
    data_sensitivity: bool = False
    #: A tenant's governance floor — raises, never lowers (V12 §40: any policy
    #: can block an action even when everything else allows it).
    tenant_policy_floor: RiskLevel | None = None


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    base_level: RiskLevel
    escalations: tuple[str, ...] = field(default=())
    unknown_action: bool = False

    def requires_durable_approval(self, actor_type: ActorType) -> bool:
        """ADR-060: who waits for a §135 approval before the effect runs.

        Humans: only HIGH/CRITICAL (LOW/MEDIUM mint server-side, invisible).
        AI agents and automation: MEDIUM and above — a governed actor never
        takes the fast path on a mutating action. SYSTEM keeps the human tier:
        internal bookkeeping must not acquire an approval dependency.
        """
        if actor_type in (ActorType.AI_AGENT, ActorType.AUTOMATION, ActorType.INTEGRATION):
            return self.level >= RiskLevel.MEDIUM
        return self.level >= RiskLevel.HIGH


#: The closed registry. V12 §16's examples first, then this system's real
#: actions — the AI tool registry (app/modules/ai/tools.py) names are the
#: authority for the tool side, and tests/test_risk_engine.py proves the two
#: registries agree.
_REGISTRY: dict[str, RiskLevel] = {
    # V12 §16 examples
    "search_products": RiskLevel.LOW,
    # Customer Agent vision tools (§12): read-only, ids never URLs
    "find_product_by_image": RiskLevel.LOW,
    "resolve_product_media": RiskLevel.LOW,
    # Sales Intelligence tools (read-only analytics; §14 read-only agent)
    "si_get_metric": RiskLevel.LOW,
    "si_compare_periods": RiskLevel.LOW,
    "si_breakdown": RiskLevel.LOW,
    "si_analyze_drivers": RiskLevel.LOW,
    "si_explain_metric": RiskLevel.LOW,
    "si_data_status": RiskLevel.LOW,
    "si_analyze_seasonality": RiskLevel.LOW,
    "si_analyze_customers": RiskLevel.LOW,
    "si_analyze_fulfillment": RiskLevel.LOW,
    "add_to_cart": RiskLevel.MEDIUM,
    "create_order": RiskLevel.HIGH,
    "send_campaign": RiskLevel.HIGH,
    "capture_payment": RiskLevel.CRITICAL,
    "refund": RiskLevel.CRITICAL,
    "delete_identity": RiskLevel.CRITICAL,
    "merge_identity": RiskLevel.CRITICAL,
    # This system's AI tools (§15 levels today; this module is their successor)
    "get_variant_price": RiskLevel.LOW,
    "check_stock": RiskLevel.LOW,
    "get_customer": RiskLevel.LOW,
    "get_order": RiskLevel.LOW,
    "search_knowledge": RiskLevel.LOW,
    "add_task": RiskLevel.MEDIUM,
    "add_tag": RiskLevel.MEDIUM,
    # Platform actions the chain will govern in later waves
    "send_message": RiskLevel.MEDIUM,
    "cancel_order": RiskLevel.HIGH,
    "rotate_secret": RiskLevel.CRITICAL,
    "delete_data": RiskLevel.CRITICAL,
}

_KNOWN_ACTIONS = frozenset(_REGISTRY)


def known_actions() -> frozenset[str]:
    """The closed registry — coverage tests read this, call sites must not."""
    return _KNOWN_ACTIONS


def classify(action: str, context: RiskContext | None = None) -> RiskAssessment:
    """Classify one action for one actor. Pure, deterministic, no I/O."""
    ctx = context or RiskContext()
    unknown = action not in _REGISTRY
    base = _REGISTRY.get(action, RiskLevel.HIGH)
    level = base
    escalations: list[str] = []

    if unknown:
        escalations.append("unknown action — failed toward caution (HIGH)")

    if ctx.amount is not None:
        if not isinstance(ctx.amount, Decimal):
            raise TypeError(f"amount must be Decimal (§47), got {type(ctx.amount).__name__}")
        if ctx.amount > MONEY_ESCALATION_THRESHOLD and level < RiskLevel.CRITICAL:
            level = RiskLevel(min(level.value + 1, RiskLevel.CRITICAL.value))
            escalations.append(f"amount {ctx.amount} > {MONEY_ESCALATION_THRESHOLD}")

    if ctx.data_sensitivity and level < RiskLevel.CRITICAL:
        level = RiskLevel(min(level.value + 1, RiskLevel.CRITICAL.value))
        escalations.append("sensitive data")

    if ctx.tenant_policy_floor is not None and ctx.tenant_policy_floor > level:
        level = ctx.tenant_policy_floor
        escalations.append("tenant policy floor")

    return RiskAssessment(
        level=level, base_level=base, escalations=tuple(escalations), unknown_action=unknown
    )
