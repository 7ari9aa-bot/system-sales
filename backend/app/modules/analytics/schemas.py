"""ANALYTICS wire contract — the response models of the canonical read surface.

Why this file exists (gap-register P8)
--------------------------------------
Every one of the eight routes in ``analytics/router.py`` was annotated
``-> dict`` with no ``response_model``, so the published OpenAPI said "an object,
keys unknown" for the whole platform-metrics surface — while this module is the
one that answers with the canonical numbers every other screen quotes. ``schemas``
turns those payloads into a contract: the field types below are the payload the
handlers build today, stated as the rule they are meant to hold.

The rule a ``response_model`` is here to enforce
------------------------------------------------
ADR-001/§47: **an AMOUNT leaves as a Decimal STRING; a COUNT and a RATIO leave as
NUMBERS.** ``_money_json``/``_as_json`` in ``router.py`` already obey it and
``test_analytics_overview.py`` / ``test_analytics_metric_parity.py`` pin that
layer — but they stop one function before the encoder, and FastAPI's default
encoder resolves a bare ``Decimal`` by casting it to ``float``. A ``MoneyStr``
field is the half that refuses a handler which forgot to format, and
``test_a_legal_window_still_binds_and_answers`` reads it off the parsed JSON.

``/analytics/metrics/{name}`` is the one payload that answers with BOTH wire
types from a single key: its ``value`` is money for the money metrics, an integer
for the counts and a float for the ratios, under the type split ``_as_json``
already applies. The field is therefore a union of the three scalar types rather
than one of them wearing the wrong coat — and it is deliberately NOT a string
everywhere, because a stringified ``conversion_rate`` would disagree with the
same ratio as ``marketing`` ships it (``budget_roas=1.5`` is a number there).

Nested arrays stay bare
-----------------------
``AnalyticsOverviewOut.daily_series`` and the ``stock`` band keep the shapes
``frontend/src/lib/queries.ts`` reads today (``OverviewDailyRow[]``); wrapping a
nested array is a frontend break for a cosmetic win, and
``test_the_nested_arrays_the_frontend_types_stay_bare`` records that decision.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

#: An amount on the wire — ``_money_json``'s own output shape, stated as a type.
#: The scale is part of the contract: every money column here is NUMERIC(14,2)
#: and every reader quantises through ``analytics.service._money``, so an amount
#: that arrives without its two decimals did not come through that path
#: (ADR-001/§47). Absent money is ``null``, never ``"0.00"``.
MoneyStr = Annotated[
    str,
    Field(
        pattern=r"^-?\d+\.\d{2}$",
        description=(
            "An amount as a Decimal STRING at the money scale (ADR-001/§47). "
            'Absent money is null, never "0.00".'
        ),
    ),
]

#: An instant rendered by the router as ``datetime.isoformat()`` AFTER it was
#: bound to UTC. Typed ``str`` rather than ``datetime`` on purpose: pydantic
#: re-spells a UTC instant's offset as ``Z``, and ``test_analytics_window_binding``
#: pins the ``+00:00`` text the window actually bound — the echoed pair has to be
#: the bind, not a re-formatting of it.
IsoInstant = Annotated[
    str,
    Field(description="ISO 8601 instant, offset-carrying (the exact text the query bound)."),
]

#: The polymorphic answer of ``GET /analytics/metrics/{name}``: an AMOUNT (a
#: Decimal string), a COUNT (an integer) or a RATIO (a float), or ``null`` when
#: the metric has no answer. Strict on purpose — a ``Decimal`` that reached here
#: unformatted is the bug this model exists to refuse, and lax arms would let
#: ``150.0`` through as money.
MetricValue = Annotated[
    MoneyStr | StrictInt | StrictFloat | None,
    Field(
        description=(
            "The metric's value: a Decimal STRING when the metric is money, a "
            "JSON number when it is a count or a ratio, null when there is no "
            "answer (ADR-001's split)."
        )
    ),
]


class ItemList(BaseModel):
    """THE list envelope, shared with ``marketing/schemas.py`` (gap P8).

    Every list these two modules return answers exactly ``{items, next_cursor}``.
    ``next_cursor`` is ``null`` on the bounded ones — a 365-day series and the
    closed metric registry genuinely have no next page, and saying so with the
    same key is what keeps the shape one shape instead of four readers.
    """

    next_cursor: str | None = Field(
        default=None,
        description="Opaque keyset cursor for the next page; null when there is none.",
    )


# ======================================================= metric registry ===


class MetricDefinitionOut(BaseModel):
    """One §167 canonical metric definition, field by field.

    The registry is the answer to "what does this number mean", so every column
    that decides an answer is published: ``filters`` is the machine-readable form
    of the predicates, and the three ``*_rule``/``*_treatment`` keys are the ones a
    reader needs to know whether it may add two figures together.
    """

    name: str
    definition: str
    source: str = Field(description="The tables the number derives from in THIS schema.")
    filters: dict[str, Any]
    timezone_rule: str = Field(description="How a calendar bucket is taken.")
    currency_rule: str
    refund_treatment: str = Field(
        description="'excluded' (gross), 'subtracted' (net), 'is_the_metric', 'not_applicable'."
    )
    version: int


class MetricDefinitionListOut(ItemList):
    """The whole registry in one call: finite, never paged, ``next_cursor`` null."""

    items: list[MetricDefinitionOut]
    next_cursor: str | None = Field(
        default=None,
        description="Always null: the registry is closed and finite, so it has no next page.",
    )


class MetricValueOut(BaseModel):
    """``GET /analytics/metrics/{metric_name}`` — one figure and its definition.

    A bare number is not an answer: the response carries the ``refund_treatment``
    and ``timezone_rule`` it was computed under, the ``basis`` when the figure is
    a ratio (so a ROAS cannot be read as return on burned spend), and the
    ``currency`` when it is money (§47 — the tenant's own, never a literal). Keys
    that do not apply to the named metric are absent, not null: the route's own
    docstring says a definition travels with the number it describes.
    """

    metric: str
    value: MetricValue
    since: IsoInstant
    until: IsoInstant
    refund_treatment: str | None = None
    timezone_rule: str | None = None
    basis: str | None = None
    currency: str | None = None


# ============================================================ money views ===


class RevenueSummaryOut(BaseModel):
    """``GET /analytics/revenue/summary`` — gross and net for one window.

    Shape honesty (§167/ADR-053): ``net_revenue`` is ``gross_revenue -
    refunded_amount`` floored at zero, and whatever could not be subtracted in
    this window comes back as ``refund_excess`` rather than disappearing. No key
    is ever named plain ``revenue``. The averages are money too, so they are
    strings beside the count that is an integer.
    """

    currency: str
    timezone: str
    timezone_source: str | None = Field(
        description=(
            "Which layer of caller -> tenants.timezone -> ANALYTICS_TIMEZONE -> UTC "
            "answered; null when the resolver reported no provenance."
        )
    )
    since: IsoInstant
    until: IsoInstant
    gross_revenue: MoneyStr
    refunded_amount: MoneyStr
    net_revenue: MoneyStr
    refund_excess: MoneyStr
    orders_count: int
    gross_aov: MoneyStr
    net_aov: MoneyStr


class DailySeriesRowOut(BaseModel):
    """One merchant-day bucket (gap M10: the day is the MERCHANT's, not UTC's)."""

    day: str = Field(description="Calendar date the bucket is labelled with, in the reported zone.")
    orders_count: int
    gross_revenue: MoneyStr
    refunded_amount: MoneyStr
    net_revenue: MoneyStr
    refund_excess: MoneyStr


class DailySeriesOut(ItemList):
    """``GET /analytics/daily-series`` — the series, under the ONE list envelope.

    It used to answer a top-level ``{items, timezone, since, ...}`` object with no
    cursor key at all, which was a fifth spelling of "a page of things". The
    paging pair is now exactly ``items`` + ``next_cursor``, and the window
    metadata rides BESIDE them: which zone the buckets were cut in, which layer
    chose it, and the two instants the query bound. Those four keys are not
    decoration — they are W5-T2's answer to "which window is this number", and a
    route that dropped them would re-open the defect ``test_analytics_window_binding``
    exists to hold shut. Hence ``extra="allow"``: the ENVELOPE is the two paging
    keys (which is what the list contract asserts) and the metadata travels with
    it unrenamed.
    """

    model_config = ConfigDict(extra="allow")

    items: list[DailySeriesRowOut]
    next_cursor: str | None = Field(
        default=None,
        description="Always null: a bounded trailing series is not a page.",
    )


class StockHealthOut(BaseModel):
    """The replenishment signal, split so an empty shelf is not "low stock" noise.

    Gap M7: a sold-out variant used to be counted as low stock, which made the
    alert mostly noise and hid what needed reordering. ``healthy_count`` is the
    remainder, so the three bands add up to what the tenant tracks.
    """

    low_stock_threshold: int
    low_stock_count: int
    out_of_stock_count: int
    healthy_count: int


class AnalyticsOverviewOut(BaseModel):
    """``GET /analytics/overview`` — the analytics screen in one call.

    A composition, not a computation: every figure comes from a reader in
    ``analytics/service.py``, and the money strings travel with it. The screen
    reads ``timezone_source``, ``stock`` and ``daily_series`` off this one object,
    so the property list is the contract; a response model that silently dropped
    a key would be worse than no response model at all, which is what
    ``test_the_overview_payload_survives_its_own_schema`` holds.
    """

    currency: str
    timezone: str
    timezone_source: str | None
    since: IsoInstant
    until: IsoInstant
    gross_revenue: MoneyStr
    refunded_amount: MoneyStr
    net_revenue: MoneyStr
    refund_excess: MoneyStr
    orders_count: int
    gross_aov: MoneyStr
    net_aov: MoneyStr
    daily_series: list[DailySeriesRowOut]
    stock: StockHealthOut


# ========================================================== §55-57 retention ===


class DropGateOut(BaseModel):
    """The shared-month gate, in the only form it may be published.

    Counts and the longest horizon, and NOTHING else: §56 partitions by time, so
    a month belongs to every tenant and one tenant may not see another's policy,
    store or existence by name.
    """

    tenant_count: int
    missing_policies: int
    max_days: int | None = Field(
        default=None,
        description=(
            "The longest horizon anyone in the deployment has chosen, or null when "
            "NO tenant has chosen yet — the gate then blocks on every tenant's "
            "silence, which is not the same answer as a zero-day horizon."
        ),
    )
    may_drop: bool
    reason: str


class RetentionPolicyRowOut(BaseModel):
    """One store's retention position for this tenant.

    ``extra="allow"`` is load-bearing, not laxness: ``policy_position`` builds a
    DATA-DRIVEN superset per store — ``keep_predicate``/``keep_reason`` exist only
    for a store that keeps rows on purpose, and ``media`` only for one whose rows
    name an object in the bucket. A strict model would DELETE the merchant's own
    evidence of why a row survives, which is the opposite of what the door is for.
    """

    model_config = ConfigDict(extra="allow")

    data_class: str
    table: str
    purge_paths: list[str] = Field(
        description="'partition' (whole months, shared) and/or 'row' (this tenant only)."
    )
    chosen: bool
    status: str | None
    retention_days: int | None = Field(
        default=None,
        description="null is 'never answered' — deliberately not a zero-day horizon.",
    )
    last_run_at: IsoInstant | None
    offered_default_days: int | None
    row_gate_reason: str | None
    legal_floor_months: int | None
    shared_gate_reason: str | None
    shared_gate_blocks_me: bool


class ChosenRetentionPolicyOut(BaseModel):
    """The row a retention write just recorded."""

    data_class: str
    retention_days: int
    status: str
    chosen: bool


class RetentionGateBlock(BaseModel):
    """The verdict and its actionable form, spelled identically on both routes.

    One definition so the read route and the write route cannot describe the same
    gate differently.
    """

    gate: DropGateOut
    blocked_reason: str | None
    unblock_requires: list[str] = Field(
        description="What would have to change for the shared month to drop; empty when it may."
    )


class RetentionPositionOut(RetentionGateBlock):
    """``GET /analytics/retention`` — this tenant's policies plus the shared gate."""

    policies: list[RetentionPolicyRowOut]


class RetentionPolicyWriteOut(RetentionGateBlock):
    """``PUT /analytics/retention/policies/{data_class}`` — the choice and the gate
    re-read after it, so the caller sees immediately whether the month is now
    droppable or still pinned by someone else's silence.
    """

    policy: ChosenRetentionPolicyOut
