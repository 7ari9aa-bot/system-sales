"""SI capabilities exposed as platform tools (spec §4).

The handlers adapt the analytics capabilities to the tool registry's
contract: (session, tenant_id, validated args) → JSON-safe dict. The
tenant comes from the platform; periods are resolved by the SYSTEM
(§6.5 — the model picks a window length, never dates); metric names are
validated against the registry and an unknown one fails the request
loudly. Each result embeds its MetricFact provenance so the orchestrator
can rebuild evidence without re-querying.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import text as _sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.guardrails import screen_inbound
from app.modules.ai.tools import ToolSpec, register_tool
from app.modules.analytics.contracts import AnalysisPeriod


async def _shop_timezone(session: AsyncSession, tenant_id: uuid.UUID):
    """The shop's reporting zone. The analytics import lives here, once, not in each tool."""
    from zoneinfo import ZoneInfo

    from app.modules.analytics.service import resolve_report_timezone

    return ZoneInfo(str(await resolve_report_timezone(session, tenant_id)))


async def _resolve_window(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    days: int,
    *,
    reference: datetime | None = None,
) -> AnalysisPeriod:
    """§6.5 — the system resolves the period in the store's configured timezone (P1-19)."""
    from app.modules.analytics.capabilities import _period_window

    zone = await _shop_timezone(session, tenant_id)
    tz_str = str(zone)
    ref = reference or datetime.now(zone)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=zone)
    else:
        ref = ref.astimezone(zone)
    period = _period_window(ref, days=days)
    return AnalysisPeriod(
        start=period.start.astimezone(UTC),
        end=period.end.astimezone(UTC),
        timezone=str(tz_str),
        attribution_basis=period.attribution_basis,
        maturity_policy=period.maturity_policy,
        maturity_status=period.maturity_status,
        data_as_of=ref.astimezone(UTC),
    )


async def _context(session: AsyncSession, tenant_id: uuid.UUID):
    """P1-18: Loads the tenant's real StoreMetricProfile instead of a blank default."""
    from app.modules.analytics.capabilities import CapabilityContext
    from app.modules.analytics.semantic import load_store_metric_profile

    profile = await load_store_metric_profile(session, tenant_id)
    return CapabilityContext(tenant_id=tenant_id, profile=profile)


def _metric_registry():
    """The analytics metric registry and the compiler's computable set, imported once.

    Every metric-name guard and the unsupported-request wrapper need these, and each import
    of another module's name is counted by the module-boundary guard, so they share this one.
    """
    from app.modules.analytics import compiler, semantic

    return semantic.all_metrics, compiler.computable_metric_names, compiler.UnsupportedFilter


def _known_metric(name: str) -> None:
    """Refuse an unregistered metric name WITH the registered ones.

    The model is a per-shop setting and may be any ordinary model, so it will sometimes guess
    a name (``revenue``). The runner shows the model only a DomainError's message; a bare
    KeyError becomes "the tool failed unexpectedly" and the model repeats the same guess until
    its tool budget is gone. Naming the registry lets it correct itself on the next call.
    """
    all_metrics, _, _ = _metric_registry()
    available = all_metrics()
    if name not in available:
        raise ValidationError(
            f"unknown metric '{name}'. Use one of these exact names: "
            + ", ".join(sorted(available))
        )


def _computable_metric(name: str) -> None:
    """Refuse a metric the tool cannot COMPUTE, offering only the ones it can.

    ``aov`` and ``net_revenue`` are registered (they can be explained) yet have no compiled
    statement, so computing them raises the compiler's bare ``UnsupportedFilter``, which the
    model hears as an unexplained failure. Listing them as "valid names" for a computing tool
    would send the model straight into the second refusal, so every message here names only
    what can actually be computed, and says why a derived metric is not on the list.
    """
    all_metrics, computable_metric_names, _ = _metric_registry()
    computable = ", ".join(sorted(computable_metric_names()))
    registered = all_metrics()
    if name not in registered:
        raise ValidationError(f"unknown metric '{name}'. Metrics you can compute: {computable}")
    if name not in computable_metric_names():
        raise ValidationError(
            f"metric '{name}' is derived from other metrics and cannot be computed directly. "
            f"Compute it from its components. Metrics you can compute: {computable}"
        )


def _fact_payload(fact) -> dict:
    """P1-20: transfers complete provenance metadata through fact payload."""
    return {
        "id": fact.id,
        "metric": fact.metric,
        "value": str(fact.value),
        "unit": fact.unit,
        # The window length is itself a measurement the answer may state
        # ("آخر 30 يوم") — without it the model cannot name the period it
        # queried without tripping the free-number gate.
        "window": f"{max((fact.period.end - fact.period.start).days, 0)}d",
        # P1-12: the split a fact belongs to is part of its meaning. Without
        # the filters, "shipments_total = 2" does not say whose two shipments
        # it is, and the model can attribute a bucket to the wrong carrier.
        "filters": fact.filters or {},
        "period_start": fact.period.start.isoformat(),
        "period_end": fact.period.end.isoformat(),
        "maturity": fact.maturity_status.value,
        "timezone": getattr(fact.period, "timezone", "UTC"),
        "source": getattr(fact, "source", "orders"),
        "attribution_basis": getattr(fact.period, "attribution_basis", "placed_at"),
        "maturity_policy": getattr(
            getattr(fact.period, "maturity_policy", None), "kind", "immediate"
        ),
        "data_as_of": fact.data_as_of.isoformat() if getattr(fact, "data_as_of", None) else None,
        "computed_at": fact.computed_at.isoformat() if getattr(fact, "computed_at", None) else None,
    }


def _evidence_store():
    """A fresh evidence store. The analytics import lives HERE, once, so a new tool does not add
    another cross-module import edge (the boundary guard counts every import statement)."""
    from app.modules.analytics.capabilities import EvidenceStore

    return EvidenceStore()


def _typed_facts(store, period, source: str, numbers) -> list[dict]:
    """P1-12: register the numbers a tool computed as typed evidence.

    `numbers` is (metric_name, value, unit, filters) per measurement. Which
    numbers may become facts — not absent, not impossible — is the analytics
    store's rule, not this adapter's; the store owns the pack contract, so a
    tool cannot mint a line the pack would refuse. This only maps what the
    store accepted into the payload shape the model reads.
    """
    ids = store.register_numbers(period, source=source, numbers=numbers)
    return [_fact_payload(store.facts[fid]) for fid in ids]


class SIGetMetricArgs(BaseModel):
    metric_name: str
    days: int = Field(default=30, ge=1, le=90)
    channel: str | None = None


async def _si_get_metric(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    days: int = 30,
    channel: str | None = None,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, get_metric

    _computable_metric(metric_name)  # refused with the names the model may use
    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    period = await _resolve_window(session, tenant_id, days)
    result = await get_metric(
        session,
        ctx,
        store,
        metric_name=metric_name,
        period=period,
        channel=channel,
    )

    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        "facts": [_fact_payload(store.facts[eid]) for eid in result.evidence_ids],
    }


class SIComparePeriodsArgs(BaseModel):
    metric_name: str
    days: int = Field(default=30, ge=1, le=90)


async def _si_compare_periods(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, compare_periods

    _computable_metric(metric_name)
    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    result = await compare_periods(session, ctx, store, metric_name=metric_name, days=days)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "facts": [
            _fact_payload(store.facts[eid]) for eid in result.evidence_ids if eid in store.facts
        ],
        "comparisons": [
            {
                "label": c.label,
                "left_fact_id": c.left_fact_id,
                "right_fact_id": c.right_fact_id,
                "delta": str(c.delta),
                "delta_pct": str(c.delta_pct) if c.delta_pct is not None else None,
            }
            for c in store.comparisons.values()
        ],
    }


class SIBreakdownArgs(BaseModel):
    metric_name: str
    dimension: str = "channel"
    days: int = Field(default=30, ge=1, le=90)


async def _si_breakdown(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    dimension: str = "channel",
    days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, breakdown_metric

    _computable_metric(metric_name)
    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    result = await breakdown_metric(
        session,
        ctx,
        store,
        metric_name=metric_name,
        dimension=dimension,
        days=days,
    )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        # P1-12: the split is a PRESENTATION of the typed facts below, not a
        # second copy of the truth. It used to read `store.dimensions`, a field
        # the evidence store never had — the tool raised AttributeError on every
        # call and the agent silently lost its only breakdown. Each bucket is
        # now a fact (value + sample size, filtered by this dimension), so the
        # model can quote a bucket only through evidence.
        "dimensions": [
            {
                "dimension": dimension,
                "entries": [
                    {"key": key, "label": key, "value": value}
                    for key, value in (result.summary.get("entries") or {}).items()
                ],
            }
        ],
        "facts": [
            _fact_payload(store.facts[eid]) for eid in result.evidence_ids if eid in store.facts
        ],
    }


class SIDriversArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_analyze_drivers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, analyze_drivers

    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    result = await analyze_drivers(session, ctx, store, days=days)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "assumptions": [a.statement for a in result.assumptions],
        "facts": [
            _fact_payload(store.facts[eid]) for eid in result.evidence_ids if eid in store.facts
        ],
        "drivers": [
            {
                "kind": d.kind,
                "orders_contribution": str(d.orders_contribution),
                "aov_contribution": str(d.aov_contribution),
                "total_delta": str(d.total_delta),
            }
            for d in store.drivers.values()
        ],
    }


class SIExplainArgs(BaseModel):
    metric_name: str


async def _si_explain_metric(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import explain_metric

    _known_metric(metric_name)
    result = explain_metric(metric_name)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
    }


class SIStatusArgs(BaseModel):
    pass


async def _si_data_status(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import get_data_status

    result = get_data_status()
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "warnings": result.data_quality.warnings,
    }


class SITopProductsArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=5, ge=1, le=20)


async def _si_top_products(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 5,
    context: dict | None = None,
) -> dict:
    """What actually sold: units and revenue per variant, with the size/color
    the buyer chose — read from the store's own order-item snapshots."""
    from app.modules.analytics.capabilities import EvidenceStore

    current = await _resolve_window(session, tenant_id, days)
    rows = (
        await session.execute(
            _sql(
                "SELECT oi.variant_id::text AS variant_id, "
                "MAX(oi.title) AS title, MAX(oi.sku) AS sku, "
                "SUM(oi.quantity) AS units, SUM(oi.total) AS revenue, "
                # a plain column: it is already in the GROUP BY, and PostgreSQL has no MAX(jsonb)
                "v.option_values AS option_values "
                "FROM order_items oi "
                "JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id "
                "LEFT JOIN product_variants v "
                "ON v.id = oi.variant_id AND v.tenant_id = oi.tenant_id "
                "WHERE oi.tenant_id = :tenant_id "
                "AND o.deleted_at IS NULL "
                "AND COALESCE(o.placed_at, o.created_at) >= :start "
                "AND COALESCE(o.placed_at, o.created_at) < :end "
                "GROUP BY oi.variant_id, v.option_values "
                "ORDER BY units DESC "
                "LIMIT :limit"
            ),
            {
                "tenant_id": str(tenant_id),
                "start": current.start,
                "end": current.end,
                "limit": limit,
            },
        )
    ).all()
    products: list[dict] = []
    for row in rows:
        options = dict(row.option_values or {})
        products.append(
            {
                "variant_id": row.variant_id,
                "title": row.title,
                "sku": row.sku,
                "size": options.get("size"),
                "color": options.get("color"),
                "option_values": options,
                "units": int(row.units),
                "revenue": str(row.revenue),
            }
        )
    store = EvidenceStore()
    facts = _typed_facts(
        store,
        current,
        "top_products",
        [
            ("products_sold_variants", len(products), "count", {}),
            *(
                (
                    "units_sold",
                    p["units"],
                    "count",
                    {"sku": p["sku"] or "", "title": p["title"] or ""},
                )
                for p in products
            ),
            *(
                (
                    "revenue",
                    p["revenue"],
                    "money",
                    {"sku": p["sku"] or "", "title": p["title"] or ""},
                )
                for p in products
            ),
        ],
    )
    return {
        "capability": "top_products",
        "status": "ok",
        "summary": {"entries": products},
        "limitations": [f"showing at most {limit} variants in this window"],
        "facts": facts,
    }


class SIStockStatusArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=25)
    stagnant_days: int = Field(default=30, ge=7, le=365)


#: A balance row per warehouse holds the stock. A variant is "tracked" when it has at least one;
#: with none, its stock is UNKNOWN, which is not the same as sold out.
_STOCK_SQL = (
    "WITH stock AS ("
    " SELECT v.id AS variant_id, p.title AS product_title, v.title AS variant_title, v.sku,"
    "  v.option_values,"
    "  COUNT(b.id) AS balance_rows,"
    "  COALESCE(SUM(b.on_hand), 0) AS on_hand,"
    "  COALESCE(SUM(b.reserved), 0) AS reserved,"
    # per warehouse, then summed: an oversold warehouse must not eat another one's stock
    "  COALESCE(SUM(GREATEST(b.on_hand - b.reserved, 0)), 0) AS available,"
    "  COALESCE(MAX(s.reorder_level), 0) AS reorder_level"
    " FROM product_variants v"
    " JOIN products p ON p.id = v.product_id AND p.tenant_id = v.tenant_id"
    " LEFT JOIN inventory_balances b ON b.variant_id = v.id AND b.tenant_id = v.tenant_id"
    " LEFT JOIN variant_stock_settings s ON s.variant_id = v.id AND s.tenant_id = v.tenant_id"
    " WHERE v.tenant_id = :tenant_id AND v.is_active AND p.status = 'active'"
    " GROUP BY v.id, p.title, v.title, v.sku, v.option_values"
    "), sold AS ("
    " SELECT DISTINCT oi.variant_id FROM order_items oi"
    " JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id"
    " WHERE oi.tenant_id = :tenant_id AND o.deleted_at IS NULL"
    "  AND o.status NOT IN ('cancelled', 'canceled')"
    "  AND COALESCE(o.placed_at, o.created_at) >= :since"
    ") "
    "SELECT st.*,"
    " (st.balance_rows > 0) AS tracked,"
    " (st.balance_rows > 0 AND st.available = 0) AS is_out,"
    " (st.balance_rows > 0 AND st.available > 0 AND st.reorder_level > 0"
    "   AND st.available <= st.reorder_level) AS is_low,"
    " (st.balance_rows > 0 AND st.available > 0 AND sd.variant_id IS NULL) AS is_stagnant "
    "FROM stock st LEFT JOIN sold sd ON sd.variant_id = st.variant_id"
)


def _stock_row(row) -> dict:
    options = dict(row.option_values or {})
    title = row.product_title or row.variant_title
    return {
        "variant_id": str(row.variant_id),
        "title": title,
        "sku": row.sku,
        "size": options.get("size"),
        "color": options.get("color"),
        "on_hand": int(row.on_hand),
        "reserved": int(row.reserved),
        "available": int(row.available),
        "reorder_level": int(row.reorder_level),
    }


async def _si_stock_status(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    limit: int = 10,
    stagnant_days: int = 30,
    context: dict | None = None,
) -> dict:
    """What is left in the shop: out, running low, sitting unsold, and not tracked at all.

    Read-only. Every figure is computed in SQL; "running low" is the shop's OWN reorder level (0 =
    the owner set none, so never called low), and an item with no balance row is "not tracked",
    never "sold out"."""
    window = await _resolve_window(session, tenant_id, 1)
    since = datetime.now(UTC) - timedelta(days=stagnant_days)
    rows = (
        await session.execute(_sql(_STOCK_SQL), {"tenant_id": str(tenant_id), "since": since})
    ).all()

    items = [_stock_row(r) for r in rows if r.tracked]
    out = [_stock_row(r) for r in rows if r.is_out]
    low = sorted((_stock_row(r) for r in rows if r.is_low), key=lambda x: x["available"])
    stagnant = sorted((_stock_row(r) for r in rows if r.is_stagnant), key=lambda x: -x["available"])
    not_tracked = [_stock_row(r) for r in rows if not r.tracked]
    counts = {
        "tracked": len(items),
        "low_stock": len(low),
        "out_of_stock": len(out),
        "stagnant": len(stagnant),
        "not_tracked": len(not_tracked),
    }
    shown_low, shown_out = low[:limit], out[:limit]
    shown_stagnant, shown_untracked = stagnant[:limit], not_tracked[:limit]
    shown_items = sorted(items, key=lambda x: x["available"])[:limit]

    limitations = []
    for name, total, shown in (
        ("running low", len(low), shown_low),
        ("out of stock", len(out), shown_out),
        ("unsold in the window", len(stagnant), shown_stagnant),
        ("not tracked", len(not_tracked), shown_untracked),
    ):
        if total > len(shown):
            limitations.append(f"showing {len(shown)} of {total} variants {name}")
    limitations.append(
        f"unsold = no non-cancelled sale in the last {stagnant_days} days; "
        "running low = at or under the shop's own reorder level (not set = never low)"
    )

    store = _evidence_store()
    facts = _typed_facts(
        store,
        window,
        "stock_status",
        [
            ("stock_tracked_variants", counts["tracked"], "count", {}),
            ("stock_low_variants", counts["low_stock"], "count", {}),
            ("stock_out_variants", counts["out_of_stock"], "count", {}),
            ("stock_stagnant_variants", counts["stagnant"], "count", {}),
            ("stock_untracked_variants", counts["not_tracked"], "count", {}),
            *(
                (
                    "stock_available",
                    r["available"],
                    "count",
                    {"sku": r["sku"] or "", "title": r["title"] or ""},
                )
                for r in shown_items + shown_low + shown_stagnant
            ),
        ],
    )
    return {
        "capability": "stock_status",
        "status": "ok",
        "summary": {
            "counts": counts,
            "items": shown_items,
            "low_stock": shown_low,
            "out_of_stock": shown_out,
            "stagnant": shown_stagnant,
            "not_tracked": shown_untracked,
        },
        "limitations": limitations,
        "facts": facts,
    }


class SIExpensesArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=366)
    limit: int = Field(default=8, ge=1, le=25)


#: POSTED expenses only: a voided one was cancelled and is not money the shop spent.
_EXPENSES_SQL = (
    "SELECT c.name AS category, e.payment_method AS method, "
    "e.amount AS amount, e.expense_date AS expense_date, e.description AS description "
    "FROM expenses e "
    "JOIN expense_categories c ON c.id = e.category_id AND c.tenant_id = e.tenant_id "
    "WHERE e.tenant_id = :tenant_id AND e.status = 'posted' "
    "AND e.expense_date >= :start_date AND e.expense_date < :end_date"
)


def _window_dates(window) -> tuple:
    """The window as plain dates, for the columns that hold a date rather than a moment."""
    return window.start.date(), window.end.date()


async def _expenses_total(session: AsyncSession, tenant_id: uuid.UUID, window) -> Decimal:
    start_date, end_date = _window_dates(window)
    rows = (
        await session.execute(
            _sql(_EXPENSES_SQL),
            {"tenant_id": str(tenant_id), "start_date": start_date, "end_date": end_date},
        )
    ).all()
    return sum((Decimal(str(r.amount)) for r in rows), Decimal(0))


async def _si_expenses_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 8,
    context: dict | None = None,
) -> dict:
    """What the shop spent in the window: total, by category, by payment method, biggest items.

    Read-only. Only POSTED expenses count (a voided one is not spending)."""
    window = await _resolve_window(session, tenant_id, days)
    start_date, end_date = _window_dates(window)
    rows = (
        await session.execute(
            _sql(_EXPENSES_SQL),
            {"tenant_id": str(tenant_id), "start_date": start_date, "end_date": end_date},
        )
    ).all()
    total = sum((Decimal(str(r.amount)) for r in rows), Decimal(0))
    by_category: dict[str, Decimal] = {}
    by_method: dict[str, Decimal] = {}
    for r in rows:
        amount = Decimal(str(r.amount))
        by_category[r.category] = by_category.get(r.category, Decimal(0)) + amount
        by_method[r.method] = by_method.get(r.method, Decimal(0)) + amount
    categories = [
        {"category": name, "total": str(value)}
        for name, value in sorted(by_category.items(), key=lambda kv: -kv[1])[:limit]
    ]
    methods = [
        {"method": name, "total": str(value)}
        for name, value in sorted(by_method.items(), key=lambda kv: -kv[1])
    ]
    biggest = [
        {
            "category": r.category,
            "description": r.description,
            "amount": str(r.amount),
            "date": r.expense_date.isoformat(),
        }
        for r in sorted(rows, key=lambda r: -Decimal(str(r.amount)))[:limit]
    ]
    store = _evidence_store()
    facts = _typed_facts(
        store,
        window,
        "expenses_summary",
        [
            ("expenses_total", total, "money", {}),
            ("expenses_count", len(rows), "count", {}),
            *(
                ("expenses_by_category", c["total"], "money", {"category": c["category"]})
                for c in categories
            ),
        ],
    )
    limitations = ["only posted expenses are counted; voided ones are left out"]
    if len(by_category) > limit:
        limitations.append(f"showing {limit} of {len(by_category)} categories")
    return {
        "capability": "expenses_summary",
        "status": "ok",
        "summary": {
            "total": str(total),
            "count": len(rows),
            "by_category": categories,
            "by_method": methods,
            "biggest": biggest,
        },
        "limitations": limitations,
        "facts": facts,
    }


class SIProfitArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=366)


#: Revenue as the shop's own sales number defines it: orders DELIVERED in the window. The line
#: total is used so revenue and cost are measured over the same lines.
_PROFIT_REVENUE_SQL = (
    "SELECT COALESCE(SUM(oi.total), 0) AS revenue, COUNT(*) AS line_count "
    "FROM order_items oi "
    "JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id "
    "WHERE oi.tenant_id = :tenant_id AND o.tenant_id = :tenant_id AND o.deleted_at IS NULL "
    "AND o.id IN ("
    " SELECT DISTINCT s.order_id FROM shipments s"
    " WHERE s.tenant_id = :tenant_id AND s.status = 'delivered'"
    " AND s.delivered_at >= :start AND s.delivered_at < :end)"
)

#: One row per sold line with its unit cost. avg_cost NULL (or no row) = UNKNOWN, never zero.
_PROFIT_LINES_SQL = (
    "SELECT oi.total AS line_total, oi.quantity AS quantity, c.avg_cost AS avg_cost "
    "FROM order_items oi "
    "JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id "
    "LEFT JOIN variant_costs c ON c.variant_id = oi.variant_id AND c.tenant_id = oi.tenant_id "
    "WHERE oi.tenant_id = :tenant_id AND o.deleted_at IS NULL "
    "AND o.id IN ("
    " SELECT DISTINCT s.order_id FROM shipments s"
    " WHERE s.tenant_id = :tenant_id AND s.status = 'delivered'"
    " AND s.delivered_at >= :start AND s.delivered_at < :end)"
)


#: A delivered order with no item rows is a real sale whose cost cannot be known. Left out of
#: the line sums it would silently look like zero revenue and a fully-costed window.
_PROFIT_EMPTY_ORDERS_SQL = (
    "SELECT COUNT(*) AS orders, COALESCE(SUM(o.grand_total), 0) AS revenue "
    "FROM orders o "
    "WHERE o.tenant_id = :tenant_id AND o.deleted_at IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM order_items oi "
    " WHERE oi.order_id = o.id AND oi.tenant_id = o.tenant_id) "
    "AND o.id IN ("
    " SELECT DISTINCT s.order_id FROM shipments s"
    " WHERE s.tenant_id = :tenant_id AND s.status = 'delivered'"
    " AND s.delivered_at >= :start AND s.delivered_at < :end)"
)


async def _si_profit_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    """Revenue, cost of goods, expenses and profit for delivered orders in the window.

    Profit is shown ONLY when the cost of every sold line is known. A variant with no recorded
    cost is unknown, not free, so when any is missing this reports how many lines and how much
    revenue are uncosted and gives NO profit figure."""
    window = await _resolve_window(session, tenant_id, days)
    params = {"tenant_id": str(tenant_id), "start": window.start, "end": window.end}
    head = (await session.execute(_sql(_PROFIT_REVENUE_SQL), params)).one()
    revenue = Decimal(str(head.revenue))
    lines = (await session.execute(_sql(_PROFIT_LINES_SQL), params)).all()
    empty = (await session.execute(_sql(_PROFIT_EMPTY_ORDERS_SQL), params)).one()
    revenue += Decimal(str(empty.revenue))

    cost = Decimal(0)
    # an order with no item rows is uncosted by definition: count it as one uncosted line
    uncosted_lines = int(empty.orders)
    uncosted_revenue = Decimal(str(empty.revenue))
    for row in lines:
        if row.avg_cost is None:
            uncosted_lines += 1
            uncosted_revenue += Decimal(str(row.line_total))
        else:
            cost += Decimal(str(row.avg_cost)) * int(row.quantity)
    expenses = await _expenses_total(session, tenant_id, window)
    profit_known = uncosted_lines == 0

    summary: dict = {
        "revenue": str(revenue),
        "line_count": len(lines),
        "profit_known": profit_known,
        "uncosted_lines": uncosted_lines,
        "uncosted_revenue": str(uncosted_revenue),
        "expenses": str(expenses),
    }
    limitations = [
        "revenue is the sum of item lines on orders delivered in the window",
        "cost uses each variant's recorded average purchase cost",
    ]
    numbers: list = [("revenue", revenue, "money", {}), ("expenses_total", expenses, "money", {})]
    if profit_known:
        gross = revenue - cost
        net = gross - expenses
        summary.update(
            {
                "cost_of_goods": str(cost),
                "gross_profit": str(gross),
                "net_profit": str(net),
            }
        )
        numbers += [
            ("cost_of_goods", cost, "money", {}),
            ("gross_profit", gross, "money", {}),
            ("net_profit", net, "money", {}),
        ]
        if net < 0:
            # register_numbers refuses a negative, so a real loss would never reach the model
            limitations.append(f"this window is a loss of {-net}; net_profit is negative")
    else:
        summary.update({"cost_of_goods": None, "gross_profit": None, "net_profit": None})
        limitations.append(
            f"profit is not shown: {uncosted_lines} sold line(s) worth {uncosted_revenue} "
            "have no recorded cost, and a missing cost is unknown, not zero"
        )
    store = _evidence_store()
    facts = _typed_facts(store, window, "profit_summary", numbers)
    return {
        "capability": "profit_summary",
        "status": "ok",
        "summary": summary,
        "limitations": limitations,
        "facts": facts,
    }


class SIPurchasingArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=366)
    limit: int = Field(default=8, ge=1, le=25)


#: Purchases in the window are RECEIVED orders only. A draft is not bought until it arrives.
_PURCHASES_SQL = (
    "SELECT po.status AS status, po.total AS total, s.name AS supplier, "
    "po.order_date AS order_date "
    "FROM purchase_orders po "
    "JOIN suppliers s ON s.id = po.supplier_id AND s.tenant_id = po.tenant_id "
    "WHERE po.tenant_id = :tenant_id AND po.status IN ('received', 'draft') "
    "AND po.order_date >= :start_date AND po.order_date < :end_date"
)

#: What each supplier is owed, by the SAME formula as the supplier statement screen:
#: received orders, minus payments (a reversal cancels one), minus accepted credit returns.
#: A standing balance, so it does not depend on the window.
_OWED_SQL = (
    "SELECT s.name AS supplier, "
    " COALESCE((SELECT SUM(po.total) FROM purchase_orders po"
    "  WHERE po.supplier_id = s.id AND po.tenant_id = s.tenant_id"
    "  AND po.status = 'received'), 0)"
    " - COALESCE((SELECT SUM(CASE WHEN sp.reverses_payment_id IS NULL"
    "  THEN sp.amount ELSE -sp.amount END) FROM supplier_payments sp"
    "  WHERE sp.supplier_id = s.id AND sp.tenant_id = s.tenant_id), 0)"
    " - COALESCE((SELECT SUM(sr.total) FROM supplier_returns sr"
    "  WHERE sr.supplier_id = s.id AND sr.tenant_id = s.tenant_id"
    "  AND sr.status = 'accepted' AND sr.settlement = 'credit'), 0) AS owed "
    "FROM suppliers s WHERE s.tenant_id = :tenant_id"
)


async def _si_purchasing_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 8,
    context: dict | None = None,
) -> dict:
    """What the shop bought in the window, what is waiting to arrive, and what it owes suppliers.

    Read-only. A draft order is waiting, not bought. The balance owed uses the same formula as the
    supplier statement, so the two screens never disagree; negative = the supplier owes the shop."""
    window = await _resolve_window(session, tenant_id, days)
    start_date, end_date = _window_dates(window)
    params = {"tenant_id": str(tenant_id)}
    owed_rows = (await session.execute(_sql(_OWED_SQL), params)).all()
    if not owed_rows:
        return {
            "capability": "purchasing_summary",
            "status": "no_data",
            "summary": {
                "purchased": "0",
                "orders_received": 0,
                "pending_orders": 0,
                "pending_value": "0",
                "total_owed": "0",
                "owed_by_supplier": [],
                "top_suppliers": [],
            },
            "limitations": ["no suppliers are recorded yet, so there are no purchases to report"],
            "facts": [],
        }
    rows = (
        await session.execute(
            _sql(_PURCHASES_SQL),
            {**params, "start_date": start_date, "end_date": end_date},
        )
    ).all()
    purchased = Decimal(0)
    received = 0
    pending = 0
    pending_value = Decimal(0)
    by_supplier: dict[str, Decimal] = {}
    for r in rows:
        total = Decimal(str(r.total))
        if r.status == "received":
            purchased += total
            received += 1
            by_supplier[r.supplier] = by_supplier.get(r.supplier, Decimal(0)) + total
        else:
            pending += 1
            pending_value += total
    top = [
        {"supplier": name, "purchased": str(value)}
        for name, value in sorted(by_supplier.items(), key=lambda kv: -kv[1])[:limit]
    ]
    balances = [(r.supplier, Decimal(str(r.owed))) for r in owed_rows]
    total_owed = sum((owed for _, owed in balances), Decimal(0))
    owed_list = [
        {"supplier": name, "owed": str(owed)}
        for name, owed in sorted((b for b in balances if b[1] != 0), key=lambda kv: -kv[1])[:limit]
    ]
    limitations = [
        "purchases are orders received in the window; drafts are waiting, not bought",
        "the balance owed is the standing total, not limited to the window",
        "total_owed is the shop's net position: a supplier that was overpaid offsets a debt",
    ]
    if any(owed < 0 for _, owed in balances):
        limitations.append("a negative balance means that supplier owes the shop")
    facts = _typed_facts(
        _evidence_store(),
        window,
        "purchasing_summary",
        [
            ("purchased_total", purchased, "money", {}),
            ("purchase_orders_received", received, "count", {}),
            ("total_owed", total_owed, "money", {}),
        ],
    )
    return {
        "capability": "purchasing_summary",
        "status": "ok",
        "summary": {
            "purchased": str(purchased),
            "orders_received": received,
            "pending_orders": pending,
            "pending_value": str(pending_value),
            "total_owed": str(total_owed),
            "owed_by_supplier": owed_list,
            "top_suppliers": top,
        },
        "limitations": limitations,
        "facts": facts,
    }


class SICashierArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=366)
    limit: int = Field(default=8, ge=1, le=25)


#: Sales are counted on ``kind = 'sale'`` receipts only: a return receipt points at the SAME order,
#: so counting every receipt would count that order's total twice. Same rule as the shift report.
_CASHIER_SALES_SQL = (
    "SELECT r.issued_at AS issued_at, r.sold_by_user_id AS sold_by, "
    "o.grand_total AS total, o.tax_total AS tax "
    "FROM pos_receipts r "
    "JOIN orders o ON o.id = r.order_id AND o.tenant_id = r.tenant_id "
    "WHERE r.tenant_id = :tenant_id AND r.kind = 'sale' "
    "AND r.issued_at >= :start AND r.issued_at < :end"
)

#: Returns come from the return lines (what was actually refunded), by the receipt's own date.
_CASHIER_RETURNS_SQL = (
    "SELECT r.id AS receipt_id, rl.refund_total AS refund "
    "FROM pos_return_lines rl "
    "JOIN pos_receipts r ON r.id = rl.receipt_id AND r.tenant_id = rl.tenant_id "
    "WHERE rl.tenant_id = :tenant_id "
    "AND r.issued_at >= :start AND r.issued_at < :end"
)

_CASHIER_SHIFTS_SQL = (
    "SELECT s.status AS status, s.cashier_user_id AS cashier, s.opened_at AS opened_at, "
    "s.closed_at AS closed_at "
    "FROM pos_sessions s WHERE s.tenant_id = :tenant_id "
    "AND (s.status = 'OPEN' OR (s.closed_at >= :start AND s.closed_at < :end))"
)

_CASHIER_REGISTERS_SQL = "SELECT COUNT(*) AS n FROM pos_registers WHERE tenant_id = :tenant_id"


async def _si_cashier_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 8,
    context: dict | None = None,
) -> dict:
    """What the till sold and refunded in the window, per cashier and per hour, and who is on shift.

    Read-only. The cashier is a sales LEDGER: it records no payment method, no cash tendered to a
    drawer count and no variance, so this reports none of those and says so."""
    window = await _resolve_window(session, tenant_id, days)
    # A till receipt exists the moment the sale happens, so unlike delivery-based metrics there is
    # nothing immature about today. The shared window stops at midnight and would answer "nothing
    # sold" for a day that has sales, so this tool runs the same length of window up to now.
    window = window.model_copy(
        update={"start": window.start + timedelta(days=1), "end": datetime.now(UTC)}
    )
    params = {"tenant_id": str(tenant_id)}
    registers = (await session.execute(_sql(_CASHIER_REGISTERS_SQL), params)).scalar_one()
    empty = {
        "invoice_count": 0,
        "sales_total": "0",
        "taxes_total": "0",
        "return_count": 0,
        "returns_total": "0",
        "net_sales": "0",
        "by_cashier": [],
        "busiest_hours": [],
        "open_shifts": [],
        "closed_shifts": 0,
    }
    if not registers:
        return {
            "capability": "cashier_summary",
            "status": "no_data",
            "summary": empty,
            "limitations": ["no cashier register is set up yet, so there are no till sales"],
            "facts": [],
        }
    win = {**params, "start": window.start, "end": window.end}
    sales = (await session.execute(_sql(_CASHIER_SALES_SQL), win)).all()
    returns = (await session.execute(_sql(_CASHIER_RETURNS_SQL), win)).all()
    shifts = (await session.execute(_sql(_CASHIER_SHIFTS_SQL), win)).all()
    zone = await _shop_timezone(session, tenant_id)

    sales_total = sum((Decimal(str(r.total)) for r in sales), Decimal(0))
    taxes_total = sum((Decimal(str(r.tax)) for r in sales), Decimal(0))
    returns_total = sum((Decimal(str(r.refund)) for r in returns), Decimal(0))
    return_count = len({r.receipt_id for r in returns})
    net = sales_total - returns_total

    per_cashier: dict[str, list] = {}
    per_hour: dict[int, int] = {}
    for r in sales:
        key = str(r.sold_by) if r.sold_by else "unknown"
        row = per_cashier.setdefault(key, [0, Decimal(0)])
        row[0] += 1
        row[1] += Decimal(str(r.total))
        hour = r.issued_at.astimezone(zone).hour
        per_hour[hour] = per_hour.get(hour, 0) + 1
    by_cashier = [
        {"cashier_id": key, "invoice_count": n, "sales_total": str(total)}
        for key, (n, total) in sorted(per_cashier.items(), key=lambda kv: -kv[1][1])[:limit]
    ]
    busiest = [
        {"hour": hour, "invoice_count": n}
        for hour, n in sorted(per_hour.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    ]
    now = datetime.now(UTC)
    open_shifts = []
    for sh in shifts:
        if sh.status == "OPEN":
            open_shifts.append(
                {
                    "cashier_id": str(sh.cashier) if sh.cashier else "unknown",
                    "opened_at": sh.opened_at.isoformat(),
                    "open_hours": int((now - sh.opened_at).total_seconds() // 3600),
                }
            )
    closed = sum(1 for sh in shifts if sh.status == "CLOSED")

    limitations = [
        "the cashier records sales and returns only: it keeps no payment method, no cash count "
        "and no drawer difference, so none of those can be reported",
        "net sales is sales minus returns made in the window, including returns of older sales",
        "the window includes today up to now: a till sale is recorded the moment it happens",
    ]
    if net < 0:
        limitations.append(f"net sales is negative ({net}): refunds exceeded sales in this window")
    if "unknown" in per_cashier:
        limitations.append("some receipts have no recorded seller, so they are listed as unknown")
    if any(sh["open_hours"] >= 24 for sh in open_shifts):
        limitations.append("a shift has been open for more than a day")
    facts = _typed_facts(
        _evidence_store(),
        window,
        "cashier_summary",
        [
            ("pos_sales_total", sales_total, "money", {}),
            ("pos_invoice_count", len(sales), "count", {}),
            ("pos_returns_total", returns_total, "money", {}),
            ("pos_net_sales", net, "money", {}),
        ],
    )
    return {
        "capability": "cashier_summary",
        "status": "ok",
        "summary": {
            "invoice_count": len(sales),
            "sales_total": str(sales_total),
            "taxes_total": str(taxes_total),
            "return_count": return_count,
            "returns_total": str(returns_total),
            "net_sales": str(net),
            "by_cashier": by_cashier,
            "busiest_hours": busiest,
            "open_shifts": open_shifts,
            "closed_shifts": closed,
        },
        "limitations": limitations,
        "facts": facts,
    }


class SICustomerActivityArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=10, ge=1, le=50)


async def _si_customer_activity(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 10,
    context: dict | None = None,
) -> dict:
    """The customers who actually contacted the store — through the customer
    agent or any channel — from the platform's own conversations."""
    from app.modules.analytics.capabilities import EvidenceStore

    current = await _resolve_window(session, tenant_id, days)
    window = {
        "tenant_id": str(tenant_id),
        "start": current.start,
        "end": current.end,
    }
    rows = (
        await session.execute(
            _sql(
                "SELECT c.id::text AS customer_id, "
                "COALESCE(c.name, '') AS name, "
                "COUNT(DISTINCT conv.id) AS conversations, "
                "COUNT(m.id) FILTER (WHERE m.direction = 'inbound') AS inbound, "
                "MAX(m.created_at) AS last_message_at "
                "FROM conversations conv "
                "JOIN customers c ON c.id = conv.customer_id AND c.tenant_id = conv.tenant_id "
                "LEFT JOIN messages m "
                "ON m.conversation_id = conv.id AND m.tenant_id = conv.tenant_id "
                "AND m.deleted_at IS NULL "
                "WHERE conv.tenant_id = :tenant_id "
                "AND conv.created_at >= :start "
                "AND conv.created_at < :end "
                "GROUP BY c.id, c.name "
                "ORDER BY inbound DESC, conversations DESC "
                "LIMIT :limit"
            ),
            {**window, "limit": limit},
        )
    ).all()
    entries = [
        {
            "customer_id": r.customer_id,
            "name": r.name,
            "conversations": int(r.conversations),
            "inbound_messages": int(r.inbound),
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
        }
        for r in rows
    ]
    totals = (
        await session.execute(
            _sql(
                "SELECT COUNT(DISTINCT conv.customer_id) AS customers, "
                "COUNT(DISTINCT conv.id) AS conversations, "
                "COUNT(m.id) FILTER (WHERE m.direction = 'inbound') AS inbound "
                "FROM conversations conv "
                "LEFT JOIN messages m "
                "ON m.conversation_id = conv.id AND m.tenant_id = conv.tenant_id "
                "AND m.deleted_at IS NULL "
                "WHERE conv.tenant_id = :tenant_id "
                "AND conv.created_at >= :start "
                "AND conv.created_at < :end"
            ),
            window,
        )
    ).first()
    store = EvidenceStore()
    facts = _typed_facts(
        store,
        current,
        "customer_activity",
        [
            ("customers_contacted", totals.customers, "count", {}),
            ("conversations_total", totals.conversations, "count", {}),
            ("inbound_messages_total", totals.inbound, "count", {}),
        ],
    )
    return {
        "capability": "customer_activity",
        "status": "ok",
        "summary": {"entries": entries[:limit]},
        "limitations": [f"showing at most {limit} customers in this window"],
        "facts": facts,
    }


class SIChannelActivityArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_channel_activity(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    """Interactions per connected platform: DM conversations and message
    volume per channel (whatsapp/instagram/messenger/telegram/webchat).

    Message counts group by the MESSAGE's own channel column — the server-
    stamped source of each message — falling back to the conversation's
    channel for rows written before the column existed."""
    from app.modules.analytics.capabilities import EvidenceStore

    current = await _resolve_window(session, tenant_id, days)
    window = {
        "tenant_id": str(tenant_id),
        "start": current.start,
        "end": current.end,
    }
    conv_rows = (
        await session.execute(
            _sql(
                "SELECT conv.channel AS channel, "
                "COUNT(DISTINCT conv.id) AS conversations, "
                "COUNT(DISTINCT conv.customer_id) AS customers "
                "FROM conversations conv "
                "WHERE conv.tenant_id = :tenant_id "
                "AND conv.created_at >= :start "
                "AND conv.created_at < :end "
                "GROUP BY conv.channel"
            ),
            window,
        )
    ).all()
    msg_rows = (
        await session.execute(
            _sql(
                "SELECT COALESCE(m.channel, conv.channel) AS channel, "
                "COUNT(*) FILTER (WHERE m.direction = 'inbound') AS inbound, "
                "COUNT(*) FILTER (WHERE m.direction = 'outbound') AS outbound, "
                "MAX(m.created_at) AS last_message_at "
                "FROM messages m "
                "JOIN conversations conv "
                "ON conv.id = m.conversation_id AND conv.tenant_id = m.tenant_id "
                "WHERE m.tenant_id = :tenant_id "
                "AND m.deleted_at IS NULL "
                "AND m.created_at >= :start "
                "AND m.created_at < :end "
                "GROUP BY 1"
            ),
            window,
        )
    ).all()
    message_stats = {r.channel: r for r in msg_rows}
    channels: list[dict] = []
    seen: set[str] = set()
    for row in conv_rows:
        seen.add(row.channel)
        stats = message_stats.get(row.channel)
        channels.append(
            {
                "channel": row.channel,
                "conversations": int(row.conversations),
                "customers": int(row.customers),
                "inbound": int(stats.inbound) if stats is not None else 0,
                "outbound": int(stats.outbound) if stats is not None else 0,
                "last_message_at": (
                    stats.last_message_at.isoformat()
                    if stats is not None and stats.last_message_at
                    else None
                ),
            }
        )
    for channel, stats in message_stats.items():
        if channel in seen:
            continue
        # A channel carrying messages but no NEW conversation in the window —
        # the interaction still happened, so it reports with zero conversations.
        channels.append(
            {
                "channel": channel,
                "conversations": 0,
                "customers": 0,
                "inbound": int(stats.inbound),
                "outbound": int(stats.outbound),
                "last_message_at": (
                    stats.last_message_at.isoformat() if stats.last_message_at else None
                ),
            }
        )
    channels.sort(key=lambda entry: (-entry["conversations"], -entry["inbound"]))
    store = EvidenceStore()
    numbers: list = []
    for entry in channels:
        scope = {"channel": entry["channel"]}
        numbers.extend(
            [
                ("conversations", entry["conversations"], "count", scope),
                ("inbound_messages", entry["inbound"], "count", scope),
                ("outbound_messages", entry["outbound"], "count", scope),
            ]
        )
    facts = _typed_facts(store, current, "channel_activity", numbers)
    return {
        "capability": "channel_activity",
        "status": "ok",
        "summary": {"entries": channels},
        "limitations": [
            "message-level analysis covers direct conversations; public post "
            "comments are read through si_social_comments"
        ],
        "facts": facts,
    }


class SISocialCommentsArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=5, ge=1, le=20)


async def _si_social_comments(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    limit: int = 5,
    context: dict | None = None,
) -> dict:
    """What the public says about the store: comment volume per platform, the
    posts that drew the most, and the latest comment texts — from the store's
    ingested social comments only (hidden/removed excluded)."""
    from app.modules.analytics.capabilities import EvidenceStore

    current = await _resolve_window(session, tenant_id, days)
    window = {
        "tenant_id": str(tenant_id),
        "start": current.start,
        "end": current.end,
    }
    per_platform = (
        await session.execute(
            _sql(
                "SELECT platform, COUNT(*) AS comments, "
                "COUNT(DISTINCT post_id) AS posts, "
                "COUNT(DISTINCT author_ref) AS commenters "
                "FROM social_comments WHERE tenant_id = :tenant_id "
                "AND commented_at >= :start "
                "AND commented_at < :end "
                "AND status = 'visible' "
                "GROUP BY platform ORDER BY comments DESC"
            ),
            window,
        )
    ).all()
    top_posts = (
        await session.execute(
            _sql(
                "SELECT platform, post_id, COUNT(*) AS comments "
                "FROM social_comments WHERE tenant_id = :tenant_id "
                "AND commented_at >= :start "
                "AND commented_at < :end "
                "AND status = 'visible' "
                "GROUP BY platform, post_id ORDER BY comments DESC "
                "LIMIT :limit"
            ),
            {**window, "limit": limit},
        )
    ).all()
    recent = (
        await session.execute(
            _sql(
                "SELECT platform, post_id, author_name, body, commented_at, permalink "
                "FROM social_comments WHERE tenant_id = :tenant_id "
                "AND commented_at >= :start "
                "AND commented_at < :end "
                "AND status = 'visible' "
                "ORDER BY commented_at DESC "
                "LIMIT :limit"
            ),
            {**window, "limit": limit},
        )
    ).all()
    platforms = [
        {
            "platform": r.platform,
            "comments": int(r.comments),
            "posts_with_comments": int(r.posts),
            "commenters": int(r.commenters),
        }
        for r in per_platform
    ]
    posts = [
        {
            "platform": r.platform,
            "post_id": r.post_id,
            "comments": int(r.comments),
        }
        for r in top_posts
    ]
    latest = []
    withheld = 0
    for r in recent:
        # A social comment is written by ANYONE on the internet and rides the
        # model context verbatim — the one untrusted-channel → SI-context path.
        # The same inbound chain that screens customer prose screens it here:
        # a non-allow verdict (instruction override, cross-tenant probing)
        # withholds the body instead of handing an owner-facing report to a
        # stranger's script. The numbers above stay untouched (they are
        # counts, not attacker-controlled text).
        verdict = screen_inbound(r.body or "")
        if verdict.decision == "allow":
            body: str | None = r.body
        else:
            body = None
            withheld += 1
        latest.append(
            {
                "platform": r.platform,
                "post_id": r.post_id,
                "author_name": r.author_name,
                "body": body,
                "commented_at": r.commented_at.isoformat() if r.commented_at else None,
                "permalink": r.permalink,
            }
        )
    store = EvidenceStore()
    numbers: list = []
    for entry in platforms:
        scope = {"platform": entry["platform"]}
        numbers.extend(
            [
                ("comments_total", entry["comments"], "count", scope),
                ("social_commenters", entry["commenters"], "count", scope),
            ]
        )
    for post in posts:
        numbers.append(
            (
                "comments_per_post",
                post["comments"],
                "count",
                {"platform": post["platform"], "post_id": post["post_id"] or ""},
            )
        )
    facts = _typed_facts(store, current, "social_comments", numbers)
    return {
        "capability": "social_comments",
        "status": "ok",
        "summary": {"per_platform": platforms, "top_posts": posts, "recent": latest},
        "limitations": [
            f"showing at most {limit} posts and {limit} recent comments; "
            "hidden and removed comments are excluded"
        ]
        + ([f"{withheld} comment body(ies) withheld by inbound screening"] if withheld else []),
        "facts": facts,
    }


#: The SI tool names in one place — the configure script and the orchestrator
#: read this tuple instead of re-listing them.
SI_TOOLS: tuple[str, ...] = (
    "si_get_metric",
    "si_compare_periods",
    "si_breakdown",
    "si_analyze_drivers",
    "si_explain_metric",
    "si_data_status",
    "si_analyze_seasonality",
    "si_analyze_customers",
    "si_analyze_fulfillment",
    "si_top_products",
    "si_customer_activity",
    "si_channel_activity",
    "si_social_comments",
    "si_stock_status",
    "si_expenses_summary",
    "si_profit_summary",
    "si_purchasing_summary",
    "si_cashier_summary",
)


def _explain_unsupported(handler):
    """Let the model hear WHY a request is unsupported instead of "failed unexpectedly".

    The compiler refuses a combination it has no statement for (a derived metric, a breakdown
    the metric lacks) with a bare ``UnsupportedFilter``. The runner shows the model only a
    DomainError's message, so a bare exception becomes an unexplained failure and the model
    retries the same request until its tool budget is gone. The compiler's messages name only
    a metric and a dimension, so they are safe to show. Nothing else is caught.
    """
    import functools

    _, _, UnsupportedFilter = _metric_registry()  # noqa: N806 - it is a class

    @functools.wraps(handler)
    async def wrapped(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except UnsupportedFilter as exc:
            raise ValidationError(str(exc)) from exc

    wrapped.explains_unsupported = True  # type: ignore[attr-defined]
    return wrapped


def register_si_tools() -> None:
    """Idempotent registration into the platform registry."""
    _, computable_metric_names, _ = _metric_registry()
    # Read from the registry the tools validate against, so the model is never told to ask for
    # a metric that does not exist (the old text said "revenue", and every model believed it).
    metrics = ", ".join(sorted(computable_metric_names()))
    specs = [
        ToolSpec(
            name="si_get_metric",
            description=f"One store metric for the last N days. Metrics: {metrics}.",
            args_schema=SIGetMetricArgs,
            handler=_si_get_metric,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_compare_periods",
            description=f"Compare a metric to the preceding equal window. Metrics: {metrics}.",
            args_schema=SIComparePeriodsArgs,
            handler=_si_compare_periods,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_breakdown",
            description=f"Split a metric by a dimension (channel). Metrics: {metrics}.",
            args_schema=SIBreakdownArgs,
            handler=_si_breakdown,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_drivers",
            description="Decompose the revenue change: orders vs AOV (exact).",
            args_schema=SIDriversArgs,
            handler=_si_analyze_drivers,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_explain_metric",
            description="How a metric is defined, attributed, and versioned.",
            args_schema=SIExplainArgs,
            handler=_si_explain_metric,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_data_status",
            description="Data freshness/maturity status for the store.",
            args_schema=SIStatusArgs,
            handler=_si_data_status,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_seasonality",
            description="Does the weekday mix explain the change? Daily revenue shape.",
            args_schema=SISeasonalityArgs,
            handler=_si_analyze_seasonality,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_customers",
            description="New vs returning customers in the window.",
            args_schema=SICustomersArgs,
            handler=_si_analyze_customers,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_fulfillment",
            description="Carrier delivery/rejection rates (minimum volume applies).",
            args_schema=SIFulfillmentArgs,
            handler=_si_analyze_fulfillment,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_top_products",
            description=(
                "Best-selling variants in the window: units, revenue, and the "
                "size/color options buyers chose."
            ),
            args_schema=SITopProductsArgs,
            handler=_si_top_products,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_stock_status",
            description=(
                "What is left in the shop: variants out of stock, running low "
                "(at or under the shop's own reorder level), sitting unsold for "
                "stagnant_days, and not tracked at all. Read-only."
            ),
            args_schema=SIStockStatusArgs,
            handler=_si_stock_status,
            tags=["sales-intelligence"],
            requires="inventory:read",
        ),
        ToolSpec(
            name="si_expenses_summary",
            description=(
                "What the shop spent in the window: total, by category, by payment "
                "method and the biggest expenses. Posted expenses only. Read-only."
            ),
            args_schema=SIExpensesArgs,
            handler=_si_expenses_summary,
            tags=["sales-intelligence"],
            requires="finance:read",
        ),
        ToolSpec(
            name="si_profit_summary",
            description=(
                "Revenue, cost of goods, expenses and profit for delivered orders. "
                "Profit is shown only when every sold item has a recorded cost; "
                "otherwise it reports how much revenue is uncosted. Read-only."
            ),
            args_schema=SIProfitArgs,
            handler=_si_profit_summary,
            tags=["sales-intelligence"],
            requires="finance:read",
        ),
        ToolSpec(
            name="si_purchasing_summary",
            description=(
                "What the shop bought in the window, orders waiting to arrive, and how "
                "much it owes each supplier. Read-only."
            ),
            args_schema=SIPurchasingArgs,
            handler=_si_purchasing_summary,
            tags=["sales-intelligence"],
            requires="purchasing:read",
        ),
        ToolSpec(
            name="si_cashier_summary",
            description=(
                "What the cashier sold and refunded in the window: totals, net, per "
                "cashier, busiest hours and open shifts. Read-only."
            ),
            args_schema=SICashierArgs,
            handler=_si_cashier_summary,
            tags=["sales-intelligence"],
            requires="orders:read",
        ),
        ToolSpec(
            name="si_customer_activity",
            description=(
                "The customers who contacted the store in the window (via any "
                "channel or the customer agent), with conversation and message "
                "counts."
            ),
            args_schema=SICustomerActivityArgs,
            handler=_si_customer_activity,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_channel_activity",
            description=(
                "Interaction volume per connected platform (whatsapp, "
                "instagram, messenger, telegram, webchat) in the window."
            ),
            args_schema=SIChannelActivityArgs,
            handler=_si_channel_activity,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_social_comments",
            description=(
                "What the public says on the store's social posts: comment "
                "volume per platform, top posts, and the latest comments."
            ),
            args_schema=SISocialCommentsArgs,
            handler=_si_social_comments,
            tags=["sales-intelligence"],
        ),
    ]
    from app.modules.ai.tools import get_tool

    for spec in specs:
        if get_tool(spec.name) is None:
            spec.handler = _explain_unsupported(spec.handler)
            register_tool(spec)


class SISeasonalityArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_analyze_seasonality(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    """§5.3 v1 — reads the store's REAL daily revenue and checks whether
    the weekday mix explains the change."""
    from decimal import Decimal

    from app.modules.analytics.capabilities import EvidenceStore, analyze_seasonality

    current = await _resolve_window(session, tenant_id, days)
    previous_start = current.start - timedelta(days=days)

    rows = (
        await session.execute(
            _sql(
                "SELECT COALESCE(o.placed_at, o.created_at)::date AS day, "
                "SUM(o.grand_total) AS revenue "
                "FROM orders o WHERE o.tenant_id = :tenant_id "
                "AND o.deleted_at IS NULL "
                "AND COALESCE(o.placed_at, o.created_at) >= :start "
                "AND COALESCE(o.placed_at, o.created_at) < :end "
                "GROUP BY day ORDER BY day"
            ),
            {"tenant_id": str(tenant_id), "start": previous_start, "end": current.end},
        )
    ).all()
    daily = {r.day: Decimal(str(r.revenue)) for r in rows}
    split_point = current.start.date()
    daily_current = {d: v for d, v in daily.items() if d >= split_point}
    daily_previous = {d: v for d, v in daily.items() if d < split_point}
    season = analyze_seasonality(daily_current, daily_previous)
    # P1-12: the gap share and each weekday lift are MEASUREMENTS of this
    # store's orders, so they are registered as facts. A summary alone lets the
    # model quote a number the pack cannot trace — the answer looks grounded
    # and is not.
    store = EvidenceStore()
    facts = _typed_facts(
        store,
        current,
        "seasonality",
        [
            (
                "seasonality_unexplained_share",
                season.summary.get("unexplained_share"),
                "ratio",
                {},
            ),
            *(
                ("weekday_revenue_lift", lift, "ratio", {"weekday": name})
                for name, lift in (season.summary.get("weekday_profile") or {}).items()
            ),
        ],
    )
    return {
        "capability": season.capability,
        "status": season.status,
        "summary": season.summary,
        "limitations": season.limitations,
        "facts": facts,
    }


class SICustomersArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


#: The hard row cap on the new/returning scan. Hitting it means the counts
#: below are computed over a truncated sample — saying so keeps a lower bound
#: from reading as the whole truth.
CUSTOMERS_SAMPLE_CAP = 5000


def _sample_cap_limitation(rows: int) -> list[str]:
    if rows < CUSTOMERS_SAMPLE_CAP:
        return []
    return [
        f"order sample capped at {CUSTOMERS_SAMPLE_CAP} rows — "
        "new/returning counts are a lower bound, not the whole window"
    ]


async def _si_analyze_customers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    """§5.4 v1 — new vs returning from the store's real orders."""

    from app.modules.analytics.capabilities import EvidenceStore, analyze_customers

    current = await _resolve_window(session, tenant_id, days)
    # The 60-day returning-customer lookahead is computed here, not as
    # ``:end + interval '60 days'``: Postgres resolves an untyped bind next to
    # an interval literal as ``interval`` itself, and the statement dies with
    # "timestamptz < interval" at prepare time.
    lookahead_end = current.end + timedelta(days=60)
    rows = (
        await session.execute(
            _sql(
                "SELECT customer_id::text AS customer_id, "
                "COALESCE(placed_at, created_at) AS placed_at "
                "FROM orders o WHERE o.tenant_id = :tenant_id "
                "AND o.deleted_at IS NULL "
                "AND COALESCE(placed_at, created_at) >= :start "
                "AND COALESCE(placed_at, created_at) < :lookahead_end "
                "ORDER BY COALESCE(placed_at, created_at) "
                "LIMIT 5000"
            ),
            {"tenant_id": str(tenant_id), "start": current.start, "lookahead_end": lookahead_end},
        )
    ).all()
    orders = [{"customer_id": r.customer_id, "placed_at": r.placed_at} for r in rows]
    result = analyze_customers(orders, window_start=current.start)
    # P1-12: the two counts are measurements of this window, so they are facts.
    store = EvidenceStore()
    facts = _typed_facts(
        store,
        current,
        "customers",
        [
            ("customers_new", result.summary.get("new"), "count", {}),
            ("customers_returning", result.summary.get("returning"), "count", {}),
        ],
    )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": list(result.limitations or []) + _sample_cap_limitation(len(orders)),
        "facts": facts,
    }


class SIFulfillmentArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    minimum_volume: int = Field(default=10, ge=1, le=100)


async def _si_analyze_fulfillment(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    minimum_volume: int = 10,
    context: dict | None = None,
) -> dict:
    """§5.7 v1 — carrier performance from the store's real shipments."""

    from app.modules.analytics.capabilities import EvidenceStore, analyze_fulfillment

    current = await _resolve_window(session, tenant_id, days)
    rows = (
        await session.execute(
            _sql(
                "SELECT s.carrier, s.status, s.shipped_at, s.delivered_at "
                "FROM shipments s "
                "JOIN orders o ON o.id = s.order_id AND o.tenant_id = s.tenant_id "
                "WHERE s.tenant_id = :tenant_id "
                "AND o.deleted_at IS NULL "
                "AND COALESCE(s.shipped_at, s.created_at) >= :start "
                "AND COALESCE(s.shipped_at, s.created_at) < :end"
            ),
            {"tenant_id": str(tenant_id), "start": current.start, "end": current.end},
        )
    ).all()
    shipments = [
        {
            "carrier": r.carrier,
            "status": r.status,
            "shipped_at": r.shipped_at,
            "delivered_at": r.delivered_at,
        }
        for r in rows
    ]
    result = analyze_fulfillment(shipments, minimum_volume=minimum_volume)
    # P1-12: per-carrier performance is measured from this store's shipments,
    # so each number becomes a fact filtered by its carrier. A small-n carrier
    # is absent from `carriers` by the minimum-volume rule, and the pack says
    # so by not holding a fact for it — the model cannot quote what was
    # deliberately not measured.
    store = EvidenceStore()
    numbers: list = []
    for row in result.summary.get("carriers") or []:
        carrier = {"carrier": row.get("carrier")}
        numbers.extend(
            [
                ("shipments_total", row.get("total"), "count", carrier),
                ("shipments_delivered", row.get("delivered"), "count", carrier),
                ("shipments_rejected", row.get("rejected"), "count", carrier),
                ("shipments_in_flight", row.get("in_flight"), "count", carrier),
                ("avg_days_to_deliver", row.get("avg_days_to_deliver"), "days", carrier),
            ]
        )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        "facts": _typed_facts(store, current, "fulfillment", numbers),
    }


register_si_tools()
