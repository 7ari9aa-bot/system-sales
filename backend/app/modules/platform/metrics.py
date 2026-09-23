"""Canonical metric definitions (spec §167).

Spec §167: "the same number must not be computed differently on different
screens." Every dashboard, report and API surface resolves its number through
this registry instead of re-deriving the SQL per screen, so two screens can
never disagree about what "revenue" or "AOV" means.

The decisions this registry makes explicit — the reason it exists:

* ``revenue`` is **gross captured** money and does **not** subtract refunds;
  ``net_revenue`` is ``revenue - refunded_amount``, FLOORED AT ZERO — a window
  cannot have negative revenue, so whatever could not be subtracted comes out as
  ``refund_excess`` rather than disappearing. They are separate names so
  a caller cannot pick "revenue" and silently get a refund-adjusted figure (or
  the reverse). ``refund_treatment`` states which is which on every row.
* A ratio names its own denominator. ``roas`` is the case in point: this schema
  records a PLANNED ``campaigns.budget`` and no burned spend at all, so the
  figure marketing publishes is a return on the plan (``basis='planned_budget'``)
  and ``spend_roas`` stays null until a real spend feed exists.
* The day boundary is the **merchant's timezone**, never UTC. Bucketing by UTC
  silently shifts the merchant's calendar day (a 23:30 sale in a UTC+2 market
  lands on the *next* UTC day), so every metric declares ``timezone_rule``.
  The concrete IANA zone is resolved from tenant settings at query time; the
  ``tenants`` table has no timezone column yet, so it is a caller-supplied
  parameter — this registry only pins the *rule*.
* Money is ``Numeric(14, 2)`` → Python ``Decimal`` in this codebase (ADR-001).
  Aggregations must stay in ``Decimal`` end to end; never round-trip money
  through ``float``, which loses cents and makes two screens disagree.

``seed_definitions`` materializes the registry into ``metric_definitions`` per
tenant so a tenant can see and version the definitions it is being measured
against. The TABLE is the tenant-visible AUDIT COPY of the in-code registry, not
a second source of truth: the registry is regenerated from code and pushed to
rows, so a row that disagrees with its ``(name, version)`` spec is a BUG and
seeding CONVERGES it (updates it) rather than skipping it. ``version`` is part of
the row's identity — re-versioning a metric writes a NEW row and leaves the prior
version as history — but every row is always an exact mirror of the spec it names.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import MetricDefinition

# --- timezone rules -------------------------------------------------------
TZ_MERCHANT = "merchant_local"  # bucket the calendar day in the merchant's zone
TZ_UTC = "utc"  # only for non-calendar durations

# --- currency rules -------------------------------------------------------
CURRENCY_PRESENTMENT = "presentment"  # keep each row's own currency; never sum across
CURRENCY_NONE = "not_applicable"

# --- refund treatment -----------------------------------------------------
REFUND_EXCLUDED = "excluded"  # gross: refunds are NOT subtracted
REFUND_SUBTRACTED = "subtracted"  # net: refunds ARE subtracted
REFUND_IS_METRIC = "is_the_metric"  # this metric *is* the refund total
REFUND_NONE = "not_applicable"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """One canonical metric definition (mirrors the metric_definitions row)."""

    name: str
    definition: str
    source: str
    filters: dict[str, Any]
    timezone_rule: str
    currency_rule: str
    refund_treatment: str
    version: int = 1

    def as_dict(self) -> dict[str, Any]:
        """Serializable form (the registry API payload / the DB row values)."""
        return {
            "name": self.name,
            "definition": self.definition,
            "source": self.source,
            "filters": self.filters,
            "timezone_rule": self.timezone_rule,
            "currency_rule": self.currency_rule,
            "refund_treatment": self.refund_treatment,
            "version": self.version,
        }


# The canonical registry — module-level constant, the single source of truth.
# `source` names the exact tables the number derives from in THIS schema.
METRIC_DEFINITIONS: tuple[MetricSpec, ...] = (
    MetricSpec(
        name="revenue",
        definition=(
            "Gross captured payment amount in the window: SUM(order_payments.amount) "
            "for captured payments, bucketed by paid_at. Refunds are NOT subtracted — "
            "use net_revenue for the refund-adjusted figure."
        ),
        source="order_payments",
        filters={"status": ["captured", "partially_refunded", "refunded"]},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_PRESENTMENT,
        refund_treatment=REFUND_EXCLUDED,
    ),
    MetricSpec(
        name="orders_count",
        definition=(
            "Count of orders placed in the window, bucketed by placed_at. Draft and "
            "cancelled orders are excluded; refunds do not change an order's existence."
        ),
        source="orders",
        filters={"status_excluded": ["draft", "cancelled"]},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_NONE,
        refund_treatment=REFUND_NONE,
    ),
    MetricSpec(
        name="aov",
        definition=(
            "Average order value: revenue / orders_count over the SAME window. Both "
            "operands resolve to this registry's definitions, so AOV can never mix a "
            "gross numerator with a net denominator."
        ),
        source="order_payments, orders",
        filters={"numerator": "revenue", "denominator": "orders_count"},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_PRESENTMENT,
        refund_treatment=REFUND_EXCLUDED,
    ),
    MetricSpec(
        name="refunded_amount",
        definition=(
            "Total refunded money in the window: SUM(refunds.amount) for approved and "
            "processed refunds, bucketed by processed_at. This metric IS the refund "
            "total (it is not itself refund-adjusted)."
        ),
        source="refunds",
        filters={"status": ["approved", "processed"]},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_PRESENTMENT,
        refund_treatment=REFUND_IS_METRIC,
    ),
    MetricSpec(
        name="net_revenue",
        definition=(
            "Refund-adjusted revenue: revenue - refunded_amount over the same "
            "window, FLOORED AT ZERO — a window's revenue is never negative, so "
            "when the refunds leaving it exceed what it collected the figure is "
            "0.00 and the un-subtractable remainder is reported as "
            "refund_excess instead of vanishing. This is the ONLY money metric "
            "that subtracts refunds; `revenue` is gross."
        ),
        source="order_payments, refunds",
        filters={
            "revenue": "revenue",
            "minus": "refunded_amount",
            "floor": "zero",
            "remainder": "refund_excess",
        },
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_PRESENTMENT,
        refund_treatment=REFUND_SUBTRACTED,
    ),
    MetricSpec(
        name="first_response_time",
        definition=(
            "Elapsed time from a customer's first inbound message to the first outbound "
            "agent or AI reply on the same conversation. A duration (seconds), not a "
            "calendar bucket; aggregated per conversation then averaged."
        ),
        source="messages, conversations",
        filters={
            "start": "messages.direction=inbound AND messages.sender_type=customer",
            "stop": "messages.direction=outbound AND messages.sender_type IN (agent, ai)",
        },
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_NONE,
        refund_treatment=REFUND_NONE,
    ),
    MetricSpec(
        name="resolution_time",
        definition=(
            "Elapsed time from a conversation's first inbound message to the moment the "
            "conversation was closed. Only conversations with status='closed' are "
            "included; still-open conversations are excluded, never counted as zero."
        ),
        source="conversations, messages",
        filters={"status": "closed"},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_NONE,
        refund_treatment=REFUND_NONE,
    ),
    MetricSpec(
        name="ai_resolution_rate",
        definition=(
            "Share of closed conversations the AI resolved without human involvement: "
            "closed conversations with no agent-authored message divided by all closed "
            "conversations. A ratio in [0, 1]."
        ),
        source="conversations, messages",
        filters={"status": "closed", "human_sender_type": "agent"},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_NONE,
        refund_treatment=REFUND_NONE,
    ),
    MetricSpec(
        name="conversion_rate",
        definition=(
            "Purchase conversions divided by touchpoints in the window: "
            "COUNT(conversions WHERE type='purchase') / COUNT(touchpoints). A ratio in "
            "[0, 1] (it may exceed 1 when a touchpoint yields multiple purchases)."
        ),
        source="conversions, touchpoints",
        filters={"conversion_type": "purchase"},
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_NONE,
        refund_treatment=REFUND_NONE,
    ),
    MetricSpec(
        name="roas",
        definition=(
            "Return on a PLAN, because true ROAS is not computable in this "
            "schema: the numerator is last-touch attributed purchase value "
            "(attributions.credited_value for model='last_touch') and the "
            "denominator is campaigns.budget — money PLANNED, not BURNED. No "
            "spend feed exists, so marketing reports basis='planned_budget' and "
            "leaves spend_roas null; burned spend can only arrive through "
            "campaign_actual_spend(), which then flips the basis. A consumer "
            "must say which budget figure it used. Refunds are not subtracted "
            "(it is a gross acquisition ratio)."
        ),
        source="attributions, conversions, touchpoints, campaigns",
        filters={
            "conversion_type": "purchase",
            "attribution_model": "last_touch",
            "planned_budget_source": "campaigns.budget",
            "actual_spend_source": "none_in_schema",
        },
        timezone_rule=TZ_MERCHANT,
        currency_rule=CURRENCY_PRESENTMENT,
        refund_treatment=REFUND_NONE,
    ),
)


class MetricRegistry:
    """Read-only access to the canonical definitions."""

    _BY_NAME: ClassVar[dict[str, MetricSpec]] = {s.name: s for s in METRIC_DEFINITIONS}

    @classmethod
    def definitions(cls) -> list[dict[str, Any]]:
        """Every canonical definition, serializable (one entry per metric)."""
        return [spec.as_dict() for spec in METRIC_DEFINITIONS]

    @classmethod
    def get(cls, name: str) -> MetricSpec | None:
        """The definition for ``name``, or ``None`` if it is not canonical."""
        return cls._BY_NAME.get(name)

    @classmethod
    def names(cls) -> list[str]:
        """Canonical metric names, in registry order."""
        return [spec.name for spec in METRIC_DEFINITIONS]


# Columns a row must carry identically to its registry spec for the row to be
# "in sync". ``(name, version)`` is the row's IDENTITY, not a synced field, and
# ``tenant_id`` is its scope — neither belongs in the UPDATE set.
_SYNCED_FIELDS: tuple[str, ...] = (
    "definition",
    "source",
    "filters",
    "timezone_rule",
    "currency_rule",
    "refund_treatment",
)


def build_seed_statement(rows: Sequence[Mapping[str, Any]]) -> Any:
    """The converging upsert that pushes registry rows into ``metric_definitions``.

    ``ON CONFLICT (tenant_id, name, version) DO UPDATE`` — NOT ``DO NOTHING``.
    The conflict target is the table's unique key (see ``uq_metric_defs`` in
    migration 8a1f6fb95fc6): ``(name, version)`` is the identity of a definition,
    so a re-versioned metric (a bumped ``version``) matches no existing row and
    lands as a NEW row, leaving the prior version as audit history. A row that
    shares the key but disagrees in any synced field is rewritten to match the
    registry. Kept separate from ``seed_definitions`` so the conflict clause is
    assertable without a database.
    """
    stmt = pg_insert(MetricDefinition).values(list(rows))
    excluded = stmt.excluded
    return stmt.on_conflict_do_update(
        index_elements=["tenant_id", "name", "version"],
        set_={
            **{field: getattr(excluded, field) for field in _SYNCED_FIELDS},
            "updated_at": func.now(),
        },
    )


def missing_or_drifted(
    existing: Mapping[tuple[str, int], Mapping[str, Any]],
    specs: Sequence[MetricSpec] = METRIC_DEFINITIONS,
) -> list[MetricSpec]:
    """Registry specs that are absent from, or disagree with, the tenant's rows.

    ``existing`` maps a row's identity ``(name, version)`` to its synced column
    values. A spec is returned when it has no row yet (missing) or when any
    synced field differs (drifted) — i.e. whenever the row is not an exact mirror
    of the registry. Pure: no I/O, so the "a changed definition must reach an
    existing tenant" rule is testable without PostgreSQL.
    """
    out: list[MetricSpec] = []
    for spec in specs:
        row = existing.get((spec.name, spec.version))
        if row is None or any(row[field] != getattr(spec, field) for field in _SYNCED_FIELDS):
            out.append(spec)
    return out


async def seed_definitions(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Materialize / converge the canonical registry for ``tenant_id``.

    The in-code registry is the authority and this table is its tenant-visible
    audit copy, so this is a push, not an insert-only first-wins seed: a
    definition whose text / source / filters / rules changed is UPDATED on the
    existing tenant's row rather than silently skipped. In-sync rows are left
    untouched (their ``updated_at`` only moves when a row actually changes).
    Idempotent — a fully converged tenant returns 0. Must run with the tenant
    GUC bound (the table is tenant-scoped and RLS applies).

    Returns the number of rows written (inserted or converged).
    """
    existing_rows = (
        await session.execute(
            select(
                MetricDefinition.name,
                MetricDefinition.version,
                *[getattr(MetricDefinition, field) for field in _SYNCED_FIELDS],
            ).where(MetricDefinition.tenant_id == tenant_id)
        )
    ).all()
    existing = {
        (r.name, r.version): {field: getattr(r, field) for field in _SYNCED_FIELDS}
        for r in existing_rows
    }
    to_write = missing_or_drifted(existing)
    if not to_write:
        return 0

    rows = [{**spec.as_dict(), "tenant_id": tenant_id} for spec in to_write]
    await session.execute(build_seed_statement(rows))
    return len(to_write)
