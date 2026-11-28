"""MARKETING wire contract — every response model and request body the module publishes.

Why this file exists (gap-register P8)
--------------------------------------
``marketing/router.py`` shipped 0 of its 14 routes with a ``response_model``, and
its campaign-analytics router (mounted at ``/analytics``, 3 more routes) 0 of 3.
Every handler was annotated ``-> dict``, which FastAPI turns into
``{"type": "object"}`` — "an object, keys unknown". Typed in Python, untyped on
the wire, and a generated client produced a contract with no fields on it. This
module is the other half of P8 for the two report-generating modules: the
published shape, stated once, in names the OpenAPI document can carry.

A ``response_model`` is not decoration here, and this is the reason
----------------------------------------------------------------------
ADR-001/§47: **an AMOUNT leaves as a Decimal STRING; a RATIO and a COUNT leave as
NUMBERS.** ``marketing/analytics.wire_money`` already obeys that, and
``test_roas.py`` / ``test_attribution_money_wire.py`` pin that layer. None of
those can see the route: FastAPI's default encoder resolves a bare ``Decimal`` by
casting it to ``float``, so a handler that forgot ``wire_money`` would ship
``150.0`` with every existing test still green. A ``str`` field with the money
scale stated in its pattern turns that into a REFUSAL at the boundary — and
``StrictFloat`` on the ratios refuses the mirror-image bug, a model that
stringified ``budget_roas`` to look conformant and then disagrees with the same
figure on the other screen.

The envelope
------------
Every list these two modules return answers exactly ``{items, next_cursor}``
(:class:`ItemList`). Four spellings existed: ``{items,next_cursor}`` (campaigns),
``{items,count}`` (campaign conversions, where ``count`` was the page length
wearing a total's name), ``{items}`` (journey runs) and a bare top-level array
(daily-orders). ``next_cursor`` is ``null`` on the bounded lists too — a 365-day
series and the closed metric registry genuinely have no next page, and saying so
with the same key is what makes the shape one shape.

The recorded exception is the composed summaries: ``revenue_by_source``,
``revenue_by_campaign``, ``campaign_budget_roas`` and ``daily_orders`` stay BARE
nested arrays, because ``frontend/src/lib/queries.ts`` types them as arrays today.
The reason is written beside the models that hold it, and
``test_the_nested_arrays_the_frontend_types_stay_bare`` keeps it from being
"unified" by a later sweep.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StrictFloat, WithJsonSchema, field_validator

#: An amount on the wire: ``wire_money``'s own output shape, stated as a type.
#: The two-decimal scale is part of the contract and not a formatting
#: preference — NUMERIC(14,2) is the column, ``Decimal("150")`` quantises to
#: "150.00", and a string that does not carry the scale did not come through
#: ``wire_money``. ``"150"`` is refused for the same reason ``150.0`` is.
MoneyStr = Annotated[
    str,
    Field(
        pattern=r"^-?\d+\.\d{2}$",
        description=(
            "An amount as a Decimal STRING at the money scale (ADR-001/§47). A "
            "client that parses money as a float64 cannot add a column of it up "
            "and still trust the cents, so the boundary hands over a string and "
            "leaves the arithmetic in Decimal. Absent money is `null`, never "
            '"0.00".'
        ),
    ),
]

#: An instant as the text this module emits (``datetime.isoformat()`` of a value
#: that is bound, in UTC, before it reaches a column). Typed ``str`` rather than
#: ``datetime`` on purpose: re-validating an instant through pydantic re-spells
#: ``+00:00`` as ``Z``, and a contract that changes the spelling of a timestamp a
#: merchant already stored is not a clarification.
IsoInstant = Annotated[
    str,
    Field(description="ISO 8601 instant, offset-carrying (the text the server stored)."),
]

#: A dimensionless share — a ROAS, an attribution weight. NOT money: a client
#: sorts and thresholds these, so they stay JSON numbers, and ``strict`` is what
#: stops ``"1.5"`` sliding in and making this screen disagree with the other one.
#: ``None`` is a real answer: no denominator is not 0.0 of return.
Ratio = Annotated[
    StrictFloat,
    Field(
        description=(
            "A ratio, NOT an amount: a JSON number a client can sort and "
            "threshold (ADR-001/§47). null when no denominator exists."
        )
    ),
]

#: Money on the REQUEST side. The published contract is a Decimal STRING — the
#: same direction ADR-001 pins on the way out — while the runtime still parses the
#: ``150`` / ``150.0`` spellings pre-P8 clients (``useCreateCampaign``) already
#: send, so widening the contract to a string cannot itself break a caller mid-
#: flight. ``Decimal`` rather than ``float`` even on that legacy path: a JSON
#: number enters as a string first, so no cent is lost on the way in either.
MoneyIn = Annotated[
    Decimal,
    WithJsonSchema(
        {
            "type": "string",
            "description": (
                "An amount as a Decimal string at the money scale, e.g. "
                '"150.00". A bare JSON number is still accepted from a pre-P8 '
                "client and parsed as Decimal, never as float64."
            ),
        }
    ),
]


# =========================================================== responses ====


class CampaignOut(BaseModel):
    """One campaign row of ``GET /marketing/campaigns``."""

    id: str
    name: str
    provider: str
    external_id: str | None
    objective: str | None
    status: str
    # None stays None: an unbudgeted campaign is not a 0.00 one.
    budget: MoneyStr | None
    created_at: IsoInstant


class ItemList(BaseModel):
    """THE list envelope for this module and its analytics sibling (gap P8).

    Four spellings of "a page of things" existed across these two modules —
    ``{items,next_cursor}``, ``{items,count}`` (where ``count`` was the page
    length wearing a total's name), ``{items}``, and a bare top-level array —
    which is four client readers for one concept. Every list these modules
    return now answers exactly these two keys.

    ``next_cursor`` is ``null`` on the bounded lists as well as on the last page
    of a paged one: a 365-day series and the closed metric registry genuinely
    have no next page, and saying so with the SAME key is what keeps the shape
    one shape. A cursor is opaque and only meaningful back to the route that
    issued it.

    Subclasses narrow ``items`` to the row model they page over; the key set
    never varies, which is what
    ``test_every_list_route_publishes_the_same_envelope`` holds.
    """

    next_cursor: str | None = Field(
        default=None,
        description="Opaque keyset cursor for the next page; null when there is none.",
    )


class CampaignListOut(ItemList):
    """``{items, next_cursor}`` — see the envelope note above."""

    items: list[CampaignOut]
    next_cursor: str | None = Field(
        default=None,
        description="Keyset cursor (created_at, id) for the next, older page.",
    )


class CampaignCreatedOut(BaseModel):
    """The reply to ``POST /marketing/campaigns`` — the row, not the list.

    Deliberately narrower than :class:`CampaignOut`: this is the echo of what the
    write accepted, and ``created_at``/``objective`` come back on the next list
    read rather than being re-derived here.
    """

    id: str
    name: str
    provider: str
    status: str
    budget: MoneyStr | None


class TouchpointCreatedOut(BaseModel):
    """A captured touchpoint: an id and the instant it was taken.

    The touchpoint's own UTM fields are not echoed — the client sent them, and
    the one thing it cannot know is the server-side ``created_at`` that first/
    last-touch attribution orders by.
    """

    id: str
    created_at: IsoInstant


class LeadOut(BaseModel):
    id: str
    status: str
    name: str | None
    phone: str | None
    source: str | None


class LeadStatusOut(BaseModel):
    """The reply to a status change: what moved, and where it is now."""

    id: str
    status: str


class ConversionOut(BaseModel):
    """One recorded conversion.

    ``value`` is an amount, so it is a Decimal string; a conversion with no
    recorded value has no money to report and stays ``null`` rather than the
    "0.00" that would read as a zero-value purchase.
    """

    id: str
    order_id: str | None
    customer_id: str | None
    type: str
    value: MoneyStr | None
    currency: str
    occurred_at: IsoInstant | None


class CampaignConversionRowOut(BaseModel):
    """A conversion this campaign took part in, and the VIEWS that credit it.

    ``attribution_models`` names which models credit the campaign. The models are
    alternative readings of the same order, so the rows are not additive — a
    reader that sums over two of them counts the money twice (§167).
    """

    id: str
    order_id: str | None
    customer_id: str | None
    type: str
    value: MoneyStr | None
    currency: str
    occurred_at: IsoInstant | None
    attribution_models: list[str]


class ConversionListOut(ItemList):
    items: list[CampaignConversionRowOut]
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Keyset cursor (created_at, id), the same scheme "
            "``GET /marketing/campaigns`` pages by. It replaced an ``offset``, "
            "which skips and repeats rows on a table where conversions arrive "
            "between two pages."
        ),
    )


class OrdersSummaryOut(BaseModel):
    """Marketing's window money — ``marketing/analytics.orders_summary``.

    Gross and net are separate keys here and no figure is called plain
    ``revenue`` (§167/ADR-053); ``orders_count`` is a count and ``weight``-like
    shares elsewhere are numbers, which is the line ``MoneyStr`` draws.
    """

    orders_count: int
    gross_revenue: MoneyStr
    refunded_amount: MoneyStr
    net_revenue: MoneyStr
    refund_excess: MoneyStr
    gross_aov: MoneyStr
    net_aov: MoneyStr
    currency: str
    timezone: str


class AttributedBySourceOut(BaseModel):
    """Last-touch ATTRIBUTED credit per source — not collected money (§167)."""

    source: str
    revenue: MoneyStr
    conversions: int


class AttributedByCampaignOut(BaseModel):
    """Last-touch attributed credit per campaign; ``campaign_id`` is ``None``
    for touchpoints that carried no campaign (the ``"unlinked"`` bucket)."""

    campaign_id: uuid.UUID | None
    campaign_name: str
    revenue: MoneyStr
    conversions: int


class RoasRowOut(BaseModel):
    """One ROI row, named for the denominator its ratio actually used.

    The two wire types meet in this one object and the split is the rule:
    ``revenue``/``planned_budget``/``actual_spend`` are amounts and are Decimal
    strings; ``budget_roas``/``spend_roas`` are dimensionless shares a client
    sorts and thresholds, so they are numbers — or ``null``, because no
    denominator is not 0.0 of return.
    """

    campaign_id: uuid.UUID
    name: str
    revenue: MoneyStr
    planned_budget: MoneyStr | None
    actual_spend: MoneyStr | None
    basis: str = Field(
        description=(
            "'planned_budget' while this schema records no burned spend; "
            "'actual_spend' only if the spend seam ever fills."
        )
    )
    budget_roas: Ratio | None
    spend_roas: Ratio | None


class MarketingSummaryOut(BaseModel):
    """``GET /analytics/summary`` — the four marketing read models, one call.

    The three nested figures are BARE arrays, and that is the recorded exception
    to :class:`ItemList`: ``frontend/src/lib/queries.ts`` types them
    ``AttributedBySource[]`` / ``AttributedByCampaign[]`` /
    ``CampaignBudgetRoas[]`` and reads them as arrays today. Wrapping a NESTED
    array is a frontend break that buys nothing the top-level envelope needed,
    so the shape stays and the reason is written here (and pinned by
    ``test_the_nested_arrays_the_frontend_types_stay_bare``).
    """

    orders_summary: OrdersSummaryOut
    revenue_by_source: list[AttributedBySourceOut]
    revenue_by_campaign: list[AttributedByCampaignOut]
    campaign_budget_roas: list[RoasRowOut]


class DailyOrderRowOut(BaseModel):
    """One merchant-day bucket (gap M10: the day is the MERCHANT's, not UTC's)."""

    day: str = Field(description="Calendar date the bucket is labelled with.")
    orders: int
    gross_revenue: MoneyStr
    refunded_amount: MoneyStr
    net_revenue: MoneyStr
    refund_excess: MoneyStr


class DailyOrderListOut(ItemList):
    items: list[DailyOrderRowOut]
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Always null: this is a bounded trailing series, not a page. The key "
            "is present so one list reader serves every list here (gap P8)."
        ),
    )


class DashboardConversationsOut(BaseModel):
    open: int
    unread: int


class DashboardOut(BaseModel):
    """``GET /analytics/dashboard`` — the home screen's one call.

    The ``orders`` block is :class:`OrdersSummaryOut`, so the money strings
    travel with it; every other scalar here is a count and stays a number.
    ``daily_orders`` and ``revenue_by_source`` are bare nested arrays because
    ``DashboardData`` in the frontend types them that way — same recorded
    exception as :class:`MarketingSummaryOut`.
    """

    orders: OrdersSummaryOut
    ai_orders_30d: int
    conversations: DashboardConversationsOut
    customers: int
    products_active: int
    # Two bands, named: a sold-out shelf used to be counted as "low stock",
    # which made the alert mostly noise and hid what needed reordering (gap M7).
    low_stock_count: int
    out_of_stock_count: int
    low_stock_threshold: int
    daily_orders: list[DailyOrderRowOut]
    revenue_by_source: list[AttributedBySourceOut]


class JourneyRunStartedOut(BaseModel):
    """The run a journey start created, at the step it starts on."""

    id: str
    journey_id: str
    customer_id: str
    status: str
    current_step: int


class JourneyRunRowOut(BaseModel):
    id: str
    customer_id: str
    status: str
    current_step: int
    started_at: IsoInstant | None
    completed_at: IsoInstant | None


class JourneyRunListOut(ItemList):
    items: list[JourneyRunRowOut]
    next_cursor: str | None = Field(
        default=None,
        description="Keyset cursor (created_at, id) for the next, older page.",
    )


class CampaignRunStartedOut(BaseModel):
    id: str
    campaign_id: str
    status: str
    total_recipients: int


class CampaignRunStateOut(BaseModel):
    """The whole reply to a pause/resume: the run and the state it moved to."""

    id: str
    status: str


class CampaignRunProgressOut(BaseModel):
    """One campaign run with its progress counters."""

    id: str
    campaign_id: str
    status: str
    total_recipients: int
    sent_count: int
    failed_count: int
    started_at: IsoInstant | None
    completed_at: IsoInstant | None


class AttributionTouchpointOut(BaseModel):
    """One touchpoint's share of one conversion.

    ``weight`` is a share of one whole and ``credited_value`` is money — they
    sit side by side in the same row precisely to prove the split is real: the
    first stays a number, the second is a string.
    """

    touchpoint_id: str
    model: str
    weight: float
    credited_value: MoneyStr


class ConversionAttributionOut(BaseModel):
    """``?conversion_id=`` — every touchpoint that credited this conversion.

    Two views of one conversion are two readings of the same money: a consumer
    picks one and never adds these rows.
    """

    conversion_id: str
    views_are_alternative: bool
    touchpoints: list[AttributionTouchpointOut]


class AttributionViewOut(BaseModel):
    model: str
    conversions: int
    credited_revenue: MoneyStr
    credits_full_value_of_each_conversion: bool
    never_sum_with_other_views: bool


class CampaignAttributionOut(BaseModel):
    """``?campaign_id=`` — the rollup, with exactly one unlabelled money figure.

    ``revenue`` is the canonical model's number; every other model is a labelled
    alternative view underneath ``never_sum_with_other_views`` (§167).
    """

    campaign_id: str
    days: int
    canonical_model: str | None
    revenue: MoneyStr
    conversions: int
    views_are_alternative: bool
    alternative_views: list[AttributionViewOut]


# =========================================================== requests ====


class CampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(default="manual", max_length=31)
    external_id: str | None = None
    objective: str | None = None
    # A planned budget IS money, so the published contract now says so: a Decimal
    # string (``MoneyIn``). The runtime still parses the number pre-P8 clients
    # post, and it parses it through ``Decimal(str(...))`` rather than float64, so
    # the leniency cannot lose a cent either way. Closing the leniency off is a
    # frontend change on its own schedule, not a silent half-step here.
    budget: MoneyIn | None = Field(default=None, ge=0)


class TouchpointRequest(BaseModel):
    customer_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=63)
    medium: str | None = Field(default=None, max_length=63)
    campaign_id: uuid.UUID | None = None
    ad_set_id: uuid.UUID | None = None
    ad_id: uuid.UUID | None = None
    click_id: str | None = None
    landing_url: str | None = None
    session_key: str | None = None


class LeadRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=31)
    email: str | None = Field(default=None, max_length=320)
    source: str | None = Field(default=None, max_length=63)
    campaign_id: uuid.UUID | None = None


class LeadStatusRequest(BaseModel):
    status: str = Field(pattern="^(new|contacted|qualified|converted|lost)$")


class ConversionRequest(BaseModel):
    customer_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    type: str = Field(default="purchase", pattern="^(purchase|signup|lead|custom)$")
    # Decimal, and the NUMERIC(14,2) shape stated explicitly: this is money.
    value: MoneyIn | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    occurred_at: datetime | None = Field(
        default=None,
        description=(
            "ISO 8601 INSTANT, offset-carrying: `2026-09-01T12:00:00Z`, or "
            "`2026-09-01T12:00:00+03:00` for a conversion timed in Cairo. A naive "
            "value is refused, because `conversions.occurred_at` is a "
            "`timestamptz` column and Postgres would read a zone-less stamp in "
            "the CONNECTION's timezone — the same wall clock would then book two "
            "different instants in two deployments, and every ROAS and "
            "attribution figure that filters on it moves with it (W5-T2's rule, "
            "applied on the write side)."
        ),
    )

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_names_its_offset(cls, value: datetime | None) -> datetime | None:
        """Refuse a wall clock before it reaches a column, never guess a zone.

        The read side of this module refuses a naive window in
        ``analytics/router._bind_window`` and ``bind_instant``; this is the same
        boundary on the path where the value becomes PERMANENT. UTC is not
        assumed on the merchant's behalf — the assumption would be exactly the
        ambiguity the refusal exists to remove.
        """
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(
                "occurred_at must be an ISO 8601 instant carrying a UTC offset "
                "(a wall clock is not an instant): send "
                "'2026-09-01T00:00:00Z' for UTC or '2026-09-01T00:00:00+03:00' "
                "for a conversion timed in Cairo time."
            )
        return value.astimezone(UTC) if value is not None else None


class JourneyStartRequest(BaseModel):
    journey_id: uuid.UUID
    customer_id: uuid.UUID


class CampaignStartRequest(BaseModel):
    campaign_id: uuid.UUID
    segment_id: uuid.UUID | None = None
    body: str | None = None
    template: str | None = None
    channel: str = "whatsapp"
