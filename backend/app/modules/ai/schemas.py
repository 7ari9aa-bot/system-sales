"""AI module API schemas — request bodies and the response contracts.

Why the response half exists (``tests/test_ai_contract.py``)
-----------------------------------------------------------
``router.py`` carries 24 routes and, before this file, 21 of its 23 body-returning
ones answered ``dict`` / ``list[dict]`` (only the two agent routes were typed, and
``AgentOut`` typed four columns of a nine-column surface). An open object is "any
key may appear, any key may be missing" — the same hole as a hand-built dict, only
documented, and it is where this module's governed state disappears on the wire:
§157's ``status``/``visibility``, §158's memory review timestamps, §135's
``payload_hash`` binding, §43's egress terms, §44's per-call evidence. Each model
below is the shape the corresponding builder actually produces —
``test_ai_contract`` compares the two sets in both directions, so a field added to
one side and not the other fails.

Money (§47/ADR-053)
-------------------
``ai_usage.cost``, ``agent_runs.cost`` and ``model_calls.cost`` are
``AI_COST = Numeric(18,8)``: eight places BELOW one cent are the column's whole
reason to exist. An AMOUNT therefore crosses JSON as a string — never a float
(a twelve-figure amount loses its sub-cent), and never ``Decimal`` either (OpenAPI
then says ``number | string``, which tells a client nothing). :data:`AmountString`
is that rule as a type, and :func:`decimal_amount` is the rendering:
``Decimal``'s own ``str`` spells a sub-cent figure ``2E-8``, which is exact but is
not the fixed-point decimal the field promises, so the value is formatted rather
than cast. Ratios and counts beside the money (``distance``, ``tokens_*``,
``latency_ms``, budget ``ratio``) stay numbers — see ``test_ai_money_wire``.

Timestamps are ``str`` because the builders emit ``datetime.isoformat()``: the
contract restates what the code already sends instead of re-parsing it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# ------------------------------------------------------------------------ money


def decimal_amount(value: object) -> object:
    """Render an amount as the plain fixed-point decimal string §47 promises.

    ``str(Decimal("0.00000002"))`` is ``"2E-8"`` — exact, but scientific spelling
    is not a decimal a client can paste into an integer-cents calculation.
    ``format(value, "f")`` keeps every place ``Numeric(18,8)`` holds (and adds no
    rounding: it never quantises, which would zero out sub-cent AI spend).
    Anything that is not a ``Decimal`` — a string a builder already rendered —
    passes through untouched.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


#: An AMOUNT as it appears in an AI response body: a decimal STRING (§47/ADR-053).
#: ``BeforeValidator`` rather than a ``str`` field because the trace service hands
#: the route ``Decimal`` values inside a bare dict; the boundary that publishes
#: bytes is where the rendering belongs.
AmountString = Annotated[str, BeforeValidator(decimal_amount)]

# ---------------------------------------------------------------- request bodies


class KnowledgeIngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source_type: str = "text"  # text | file | url | qa
    source_ref: str | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    model: str | None = Field(default=None, max_length=127)
    system_prompt: str | None = None
    description: str | None = None


# --------------------------------------------------------------- knowledge (§157)


class KnowledgeIngested(BaseModel):
    """What an ingest actually decided about the row's governance state.

    ``visibility`` is not decoration: retrieval filters on it BEFORE a row may
    reach a model's context, so the write echo has to carry it or the reviewer
    cannot see what they just published.
    """

    id: UUID
    status: str = Field(description="pending | indexed | failed")
    visibility: str = Field(
        description="§157: customer_facing | staff_only | internal | admin_only"
    )


class KnowledgeItemOut(BaseModel):
    """One row of the review list — both governance columns included."""

    id: UUID
    title: str
    source_type: str
    source_ref: str | None
    status: str
    visibility: str
    created_at: str


class KnowledgeList(BaseModel):
    items: list[KnowledgeItemOut]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque keyset position; pass it back as `cursor`.",
    )


class KnowledgeSearchHit(BaseModel):
    """One ranked hit. ``distance`` is a score, not an amount — it stays a number."""

    id: UUID
    title: str
    source_type: str
    content: str
    distance: float
    visibility: str


# --------------------------------------------------------------------- agents


class AgentOut(BaseModel):
    """One agent, as the tenant surface describes it.

    Two halves, both load-bearing. The guardrail block MUST be reachable:
    ``run_limits`` is the per-agent execution ceiling (§44/§135),
    ``temperature``/``max_output_tokens`` shape every call, ``is_active`` is the
    kill switch and ``version`` is the concurrency token — ``is_active`` alone is
    not "the governance state of this agent".

    ``system_prompt`` MUST NOT be: ``GET /ai/agents`` is gated on tenant
    authentication only, not on ``settings:write``, so anything in this model is
    readable by every member of the tenant. The prompt is a business secret, not
    governance state, so it stays on the row and off the contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    model: str | None
    temperature: float
    max_output_tokens: int | None
    run_limits: dict[str, Any] = Field(
        description="Per-agent execution guardrails; omitted keys use runtime defaults."
    )
    is_active: bool
    version: int


class ToolCallOut(BaseModel):
    name: str
    status: str
    error: str | None = None


# ------------------------------------------------------------------ memories 158


class MemoryOut(BaseModel):
    """§158: the review surface IS a state machine, so the state is the contract.

    ``source`` is the provenance that separates "customer said X" from "system
    verified X"; the three timestamps are the audit trail of the review. A claim
    whose retirement stamp can quietly stop being sent is not reviewable, which
    is why every field here is declared and the builder in ``router.py`` is
    compared against it in both directions.
    """

    id: UUID
    kind: str = Field(description="summary | preference | fact")
    content: str
    source: str = Field(
        description="customer_stated | system_verified | agent_inferred | staff_entered"
    )
    status: str = Field(description="active | invalidated")
    confidence: float | None
    customer_id: UUID | None
    conversation_id: UUID | None
    actor_id: UUID | None = Field(description="§158: which staff member wrote the claim.")
    created_at: str | None
    verified_at: str | None
    invalidated_at: str | None
    expires_at: str | None


class MemoryList(BaseModel):
    items: list[MemoryOut]
    next_cursor: str | None = Field(default=None, description="Keyset position, or None.")


# ------------------------------------------------------------------ approvals 135


class ApprovalOut(BaseModel):
    """One row of the §135 queue, with the binding that makes it a decision.

    ``payload_hash`` is the SHA-256 of the arguments the human approved; without
    it on the wire a reviewer cannot tell an approval that covers
    ``create_order(quantity=1)`` from one that covers the action NAME (gate review
    G-02). ``approved_by_user_id``/``decided_at``/``consumed_at`` are who, when and
    whether the grant was actually spent.
    """

    id: UUID
    status: str = Field(description="PENDING | APPROVED | REJECTED | EXPIRED | CANCELLED")
    action: str
    risk_level: str = Field(description="LOW | MEDIUM | HIGH")
    entity_type: str
    entity_id: str
    conversation_id: UUID | None
    run_id: UUID | None
    payload: dict[str, Any]
    payload_hash: str | None = Field(
        default=None,
        description="§135 G-02: digest of the approved arguments. NULL means the "
        "approval is unbound and the gate will not match it.",
    )
    requested_by: str
    expires_at: str | None
    decided_at: str | None
    consumed_at: str | None
    approved_by_user_id: UUID | None
    rejection_reason: str | None
    created_at: str | None


class ApprovalList(BaseModel):
    """The queue, and whether it is longer than what it shows."""

    items: list[ApprovalOut]
    truncated: bool = Field(
        description="True when the page was cut: §135's queue must never present a "
        "bounded read as the complete set of decisions owed."
    )


class ApprovalDecisionOut(ApprovalOut):
    """The decide echo: the same approval, plus what the decision did to the run."""

    resumed: bool = Field(
        description="True when approving re-enqueued the conversation for the gated action."
    )


# ----------------------------------------------------------------- provider policy


class PolicyOut(BaseModel):
    """§43 egress governance for one provider — every term staff may declare."""

    id: UUID
    provider: str
    status: str = Field(description="allowed | denied")
    allowed_models: list[str]
    pii_redaction_required: bool
    data_classification: str
    data_residency: str | None = Field(description="§43 region the data may not leave.")
    retention_terms: str | None = Field(description="§43 documented provider retention terms.")
    notes: str | None
    updated_at: str | None


class PolicyList(BaseModel):
    items: list[PolicyOut]


# ------------------------------------------------------------------- evaluations


class EvaluationOut(BaseModel):
    """§169: one evaluation, including the rollout state that gates the canary."""

    id: UUID
    agent_id: UUID
    prompt_version: int
    dataset_ref: str | None
    status: str = Field(description="pending | running | passed | failed | approved | rolled_back")
    quality_metrics: dict[str, Any]
    rollout_status: str = Field(description="none | canary[_pct] | full | rolled_back")
    notes: str | None
    created_at: str | None
    updated_at: str | None


class EvaluationList(BaseModel):
    items: list[EvaluationOut]


# ------------------------------------------------------------------------- trace


class TraceModelCallOut(BaseModel):
    """One provider call: the §44 evidence, with its cost as money (§47)."""

    id: UUID
    alias: str | None
    provider: str | None
    model: str | None
    tokens_in: int
    tokens_out: int
    cost: AmountString
    latency_ms: int | None
    status: str


class TraceToolCallOut(BaseModel):
    id: UUID
    name: str
    status: str
    error: str | None
    duration_ms: int | None
    result: dict[str, Any] | None


class TraceRunSummaryOut(BaseModel):
    """The run-level fields — the list shape :meth:`AITraceService.by_correlation`
    returns, and the base of the admin view below."""

    run_id: UUID
    agent_id: UUID
    conversation_id: UUID | None
    status: str
    tokens_in: int
    tokens_out: int
    cost: AmountString
    error: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str | None
    correlation_id: str | None = Field(
        description="Resolved from the run's input JSONB — agent_runs has no such column."
    )
    causation_id: str | None = Field(
        description="Resolved from the run's input JSONB — agent_runs has no such column."
    )


class TraceRunOut(TraceRunSummaryOut):
    """One run with its model and tool children (§44's admin view).

    ``prompt_version``/``retries``/``policy_decisions``/``request_id`` are the
    §44 fields the schema records nowhere; the service reports them as None/[]
    rather than inventing a column, and they stay present so the shape is stable.
    """

    model: str | None
    provider: str | None
    alias: str | None
    latency_ms: int | None
    model_latency_ms: int
    fallback: bool
    tools: list[str]
    errors: list[str]
    model_calls: list[TraceModelCallOut]
    tool_calls: list[TraceToolCallOut]
    prompt_version: int | None
    retries: int | None
    policy_decisions: list[dict[str, Any]]
    request_id: str | None


class TraceSummaryOut(BaseModel):
    """The rollup. ``total_cost`` is money; the counts beside it are counts."""

    days: int
    since: str
    runs: int
    failures: int
    fallback_count: int
    tokens_in: int
    tokens_out: int
    total_tokens: int
    total_cost: AmountString


class TraceCorrelationOut(BaseModel):
    """Every run that belongs to one customer interaction — how a handoff is followed."""

    correlation_id: str
    runs: list[TraceRunSummaryOut]


# -------------------------------------------------------------------- usage §47/55


class UsageDayOut(BaseModel):
    date: str
    tokens_in: int
    tokens_out: int
    cost: AmountString


class UsageTotalsOut(BaseModel):
    """The period total the ROUTE computes (§55 forbids the browser from doing it)."""

    cost: AmountString
    tokens_in: int
    tokens_out: int


class UsageSummaryOut(BaseModel):
    days: int
    summary: list[UsageDayOut]
    totals: UsageTotalsOut
