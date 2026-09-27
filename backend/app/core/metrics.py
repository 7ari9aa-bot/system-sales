"""Operational metrics: a Prometheus text-format exposition of what we already know.

O10 records "no ``/metrics``". Verified before writing this:
``GET /api/v1/platform/metrics`` answers from the BUSINESS metric registry
(``app/modules/platform/metrics.py`` — revenue, ROAS, pipeline), and the string
``prometheus`` appears nowhere in the tree. There is no operational exposition,
and ``prometheus_client`` is not a dependency — so the format is rendered here
by hand rather than adding a runtime dependency for five series.

WHAT GETS EXPOSED, AND THE RULE FOR ADDING MORE
-----------------------------------------------
Only a signal that already exists. Two kinds:

* a counter for a log event the worker runtime already emits —
  ``worker.deferred``, ``worker.handle_failed``, ``worker.permanent_failure``,
  ``worker.idempotent_skip``, ``worker.inbox_contended``, and the §144
  WORKER_SECONDS charge ``_charge_worker_seconds`` already computes. Counting
  one of those is not a new instrument; it is the same fact, scrape-able.
* a gauge for an aggregate the health surface already computes — the outbox
  backlog (``min(created_at)`` of unpublished rows) and the DLQ depth
  (``XLEN`` per dead-letter stream).

Nothing is invented. In particular ``rate_limit_rejections_total`` and
``idempotency_conflicts_total`` are DELIBERATELY ABSENT: the only code that
observes those outcomes lives in ``app/core/middleware.py`` and
``app/core/idempotency.py``, neither of which this lane owns, and NOTHING
persists a rejection today (the rate limiter keeps only sliding-window ZSETs,
which expire; ``idempotency_keys`` records processed/failed, never "conflict").
Emitting a series that can only read zero would be fake-green, so
``tests/test_metrics_exposition.py`` asserts their absence instead.

WHY THE COUNTERS LIVE IN REDIS
------------------------------
The workers and the API are separate processes
(``python -m app.workers.run`` versus uvicorn). An in-process registry would
put every worker number where no scraper can reach it. Redis is already this
codebase's shared counter store — ``app.core.fairness`` keeps the §144 budgets
there and fails open when it is unreachable — so the same pattern, with the
same fail-open rule for the write path, applies here.

Layout: one Redis HASH per metric,
``metrics:{name}`` → field is the label values in DECLARED order joined by
``|`` → value is the running total. ``HGETALL`` renders a whole metric in one
round trip, and no keyspace scan is ever needed on the scrape path.

THE EXPOSURE RULE
-----------------
``outbox_events`` and ``idempotency_keys`` are on the ``_RLS_EXEMPT`` list in
migration ``b2c3d4e5f6a7`` — the runtime role reads them across tenants so the
relay can work. That is what makes a platform-wide backlog computable, and it
is also the leak risk: an endpoint with no tenant context is showing
cross-tenant state.

Two containment properties, both pinned by tests:

1. **Aggregates only.** ``CATALOGUE`` declares every label name, and each must
   be on ``ALLOWED_LABEL_KEYS``. There is no tenant/user/customer/workspace/
   location/aggregate/correlation label, and adding one fails the catalogue
   test instead of shipping.
2. **Values are shape-checked.** A label value must match
   ``[A-Za-z0-9_.:/-]{1,64}`` — so a UUID tenant id, an email address or a phone
   number passed as a value is refused even under a permitted label name.

And the route: it takes no tenant context at all (no dependency, one parameter),
is unauthenticated only outside ``is_secure_environment``, and in a secure
environment requires ``Authorization: Bearer <SERVICE_TOKEN_INTERNAL>`` — the
same credential ``app.main._RequestIDMiddleware`` already recognizes for
internal callers. No token configured in a secure environment answers 503 rather
than degrading to an open endpoint.
"""

from __future__ import annotations

import hmac
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.events.bus import DLQ_SUFFIX

logger = logging.getLogger(__name__)

#: Prometheus text-format version this renders. Scrapers key off it.
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: Redis keyspace for the counters. One HASH per metric name.
REDIS_KEY_PREFIX = "metrics"

#: Field separator inside a metric hash. ``|`` cannot appear in a value that
#: passes ``_VALUE_RE``, so fields never collide.
LABEL_SEPARATOR = "|"

#: The ONLY label names any series may carry. Everything outside this set can
#: address a customer; see the module docstring's exposure rule.
ALLOWED_LABEL_KEYS: frozenset[str] = frozenset({"stream", "outcome", "collector"})

#: Closed value set for ``worker_events_total{outcome}``. Kept closed because an
#: open value here is a cardinality bomb on a hot path — and because a typo that
#: silently creates a new series is worse than a raised error.
EVENT_OUTCOMES: frozenset[str] = frozenset(
    {"processed", "retried", "dead_lettered", "deferred", "skipped", "contested"}
)


#: A label value that cannot carry structure the exposition format hates: no
#: spaces, no braces, no quotes, no newline, at most 64 characters. This catches
#: emails, phone numbers and free text — but NOT a bare UUID, which is pure
#: [0-9a-f-] and slips straight through. The closed sets below are what stop a
#: tenant id riding in as a `stream`; this regex only keeps the text renderable.
_VALUE_RE = re.compile(r"[A-Za-z0-9_.:/-]{1,64}")
_NAME_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")

# The streams the shipped pools consume. Derived list lives in
# ``app/workers/run.py:POOLS``; core must not import workers, so the tuple is
# declared here and tests/test_worker_metrics_counters.py pins it against POOLS
# — a new pool that forgets to register its DLQ here goes red.
POOL_STREAMS: tuple[str, ...] = (
    "message.events",
    "notification.events",
    "webhook.events",
    "campaign_run.events",
    "platform.events",
)
POOL_DLQ_STREAMS: tuple[str, ...] = tuple(s + DLQ_SUFFIX for s in POOL_STREAMS)

#: The closed set behind every `stream` label. This, not the value regex, is what
#: refuses `stream="11111111-1111-…"` — a tenant UUID is legal [0-9a-f-] text and
#: passes the shape check untouched, so without a closed set the exposition would
#: publish one series per tenant. Cost of the closedness: a new pool must be added
#: to POOL_STREAMS in the same change, and ``tests/test_worker_deployment_declaration.py``
#: is where a drift between the two lists becomes a red test rather than an
#: invisible metric.
STREAM_LABEL_VALUES: frozenset[str] = frozenset(POOL_STREAMS + POOL_DLQ_STREAMS)


class MetricDefinitionError(RuntimeError):
    """The metric or its labels are not in the catalogue — a coding error."""


class MetricValueError(MetricDefinitionError):
    """A label VALUE is outside the shape the exposure rule allows."""


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    help_text: str
    type: str  # "counter" | "gauge"
    label_names: tuple[str, ...] = ()
    #: Closed value sets, by label name. Empty means "shape-check only".
    allowed_values: Mapping[str, Iterable[str]] = field(default_factory=dict)


CATALOGUE: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        name="outbox_pending_total",
        help_text="Outbox rows not yet durably published (pending/publishing/failed).",
        type="gauge",
    ),
    MetricDefinition(
        name="outbox_oldest_pending_seconds",
        help_text="Age in seconds of the oldest unpublished outbox row; 0 when idle.",
        type="gauge",
    ),
    MetricDefinition(
        name="dlq_depth",
        help_text="Entries on each worker dead-letter stream (Redis XLEN).",
        type="gauge",
        label_names=("stream",),
        allowed_values={"stream": STREAM_LABEL_VALUES},
    ),
    MetricDefinition(
        name="worker_events_total",
        help_text="Events a worker pool finished with, per outcome.",
        type="counter",
        label_names=("stream", "outcome"),
        allowed_values={"stream": STREAM_LABEL_VALUES, "outcome": EVENT_OUTCOMES},
    ),
    MetricDefinition(
        name="worker_seconds_total",
        help_text="Worker seconds consumed, the §144 metered charge, per stream.",
        type="counter",
        label_names=("stream",),
        allowed_values={"stream": STREAM_LABEL_VALUES},
    ),
    MetricDefinition(
        name="metrics_collection_failures_total",
        help_text=(
            "Times a collector could not answer, so an absent series never reads "
            "as a healthy zero."
        ),
        type="counter",
        label_names=("collector",),
    ),
    # V12 Correctness SLOs (Invariant 62)
    MetricDefinition(
        name="decision_stale_total",
        help_text="Decisions transitioned to STALE due to TTL expiration or invalidated evidence.",
        type="counter",
    ),
    MetricDefinition(
        name="authority_rejection_total",
        help_text="Authority lease minting or redemption rejections.",
        type="counter",
    ),
    MetricDefinition(
        name="version_conflict_total",
        help_text="Optimistic concurrency or resource version conflicts detected during execution.",
        type="counter",
    ),
    MetricDefinition(
        name="budget_fail_total",
        help_text="Budget reservation or limit exhaustion failures.",
        type="counter",
    ),
)

_BY_NAME: dict[str, MetricDefinition] = {m.name: m for m in CATALOGUE}


# ------------------------------------------------------------------ backends


def _default_redis() -> Any:
    from app.core.redis import get_redis

    return get_redis()


def _default_session_factory() -> Any:
    from app.core.db import get_sessionmaker

    return get_sessionmaker()


def _settings_for_metrics() -> Any:
    """The seam the route reads config through (and the tests replace).

    Inline ``get_settings()`` in a handler would make the authentication rule
    untestable without flipping ``ENVIRONMENT`` process-wide.
    """
    from app.core.config import get_settings

    return get_settings()


# ----------------------------------------------------------------- validating


def _definition(name: str) -> MetricDefinition:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise MetricDefinitionError(
            f"{name!r} is not in app.core.metrics.CATALOGUE — expose an existing "
            f"signal or add a deliberate definition, never write a stray series"
        ) from exc


def _validate(name: str, labels: Mapping[str, Any]) -> dict[str, str]:
    """Everything about one write that is a programming error, checked eagerly.

    Raises rather than dropping so a mistyped label cannot become an invisible
    series. This is deliberately OUTSIDE the fail-open wrapper in
    :func:`increment`: Redis being down is an infrastructure event, a wrong
    label is a bug.
    """
    definition = _definition(name)
    declared = definition.label_names
    given = tuple(labels)
    if set(given) != set(declared):
        raise MetricDefinitionError(
            f"{name} takes labels {declared!r}, got {given!r}"
        )
    for key in declared:
        if key not in ALLOWED_LABEL_KEYS:
            raise MetricDefinitionError(
                f"label {key!r} on {name} is not on ALLOWED_LABEL_KEYS — a label "
                f"that can name a tenant is the leak this module exists to prevent"
            )
        raw = labels[key]
        value = str(raw)
        if not _VALUE_RE.fullmatch(value):
            raise MetricValueError(
                f"{name}{{{key}={value!r}}} is not a safe label value: "
                f"[A-Za-z0-9_.:/-]{{1,64}} only, so identifiers cannot ride in"
            )
        allowed = definition.allowed_values.get(key)
        if allowed is not None and value not in set(allowed):
            raise MetricValueError(
                f"{name}{{{key}={value!r}}}: outcome is a closed set "
                f"{sorted(allowed)}"
            )
    return {key: str(labels[key]) for key in declared}


def _field_for(definition: MetricDefinition, labels: Mapping[str, str]) -> str:
    if not definition.label_names:
        return "_"
    return LABEL_SEPARATOR.join(labels[key] for key in definition.label_names)


def _key(name: str) -> str:
    return f"{REDIS_KEY_PREFIX}:{name}"


# ------------------------------------------------------------------- writing


async def increment(
    name: str,
    *,
    value: float = 1.0,
    redis: Any = None,
    strict: bool = True,
    labels: Mapping[str, Any] | None = None,
    **label_kwargs: Any,
) -> None:
    """Add ``value`` to a counter in the shared store.

    ``strict`` splits the two failure classes: a validation problem ALWAYS
    raises (it is a bug at the call site), a Redis problem raises only for
    callers that care. The worker runtime passes ``strict=False`` — a metrics
    outage must never take a pool down, which is the same rule
    ``app.core.fairness.consume`` runs on.
    """
    merged: dict[str, Any] = dict(labels or {})
    merged.update(label_kwargs)
    safe_labels = _validate(name, merged)
    definition = _BY_NAME[name]
    if definition.type != "counter":
        raise MetricDefinitionError(
            f"{name} is a {definition.type}: its value is a measurement, "
            f"not something to increment"
        )
    if value < 0:
        raise MetricDefinitionError(f"{name}: counters only go up, got {value!r}")

    client = redis if redis is not None else _default_redis()
    try:
        await client.hincrbyfloat(_key(name), _field_for(definition, safe_labels), value)
    except Exception as exc:  # noqa: BLE001 — the counter is never worth a failure
        if strict:
            raise
        logger.debug("metrics.increment_failed name=%s err=%s", name, exc)


async def record_decision_stale(*, redis: Any = None, count: float = 1.0) -> None:
    """Record Invariant 62: decision TTL or evidence invalidation stale transition."""
    await increment("decision_stale_total", value=count, redis=redis, strict=False)


async def record_authority_rejection(*, redis: Any = None, count: float = 1.0) -> None:
    """Record Invariant 62: authority lease minting or redemption rejection."""
    await increment("authority_rejection_total", value=count, redis=redis, strict=False)


async def record_version_conflict(*, redis: Any = None, count: float = 1.0) -> None:
    """Record Invariant 62: optimistic concurrency / resource version conflict."""
    await increment("version_conflict_total", value=count, redis=redis, strict=False)


async def record_budget_fail(*, redis: Any = None, count: float = 1.0) -> None:
    """Record Invariant 62: budget reservation or exhaustion failure."""
    await increment("budget_fail_total", value=count, redis=redis, strict=False)


# -------------------------------------------------------------------- reading


@dataclass(frozen=True)
class Sample:
    """One rendered line: ``name{l=v,...} value``."""

    name: str
    value: float | int | str
    labels: Mapping[str, str]
    type: str
    help_text: str


def _as_float(raw: Any) -> float | str:
    """Keep an exact Redis total as text when it round-trips as a number.

    HINCRBYFLOAT answers "5" for 5 and "45.5" for 45.5; re-typing through
    ``float`` would print 45.5 as "45.5" anyway but would turn a 1e21 total into
    scientific notation Prometheus scrapers may not accept. The validated string
    is what the exposition promises.
    """
    text = str(raw).strip()
    try:
        Decimal(text)
    except (InvalidOperation, ValueError):
        return 0.0
    return text


async def _read_counter(definition: MetricDefinition, client: Any) -> list[Sample]:
    try:
        stored: Mapping[str, Any] = await client.hgetall(_key(definition.name))
    except Exception as exc:  # noqa: BLE001 — one store failure is not no metrics
        logger.debug("metrics.read_failed name=%s err=%s", definition.name, exc)
        raise
    if not stored:
        return []
    samples: list[Sample] = []
    for encoded_field, raw in stored.items():
        parts = str(encoded_field).split(LABEL_SEPARATOR)
        if definition.label_names and len(parts) != len(definition.label_names):
            continue  # written by a different label shape; skip, never mislabel
        labels = (
            {}
            if not definition.label_names
            else dict(zip(definition.label_names, parts, strict=True))
        )
        samples.append(
            Sample(
                name=definition.name,
                value=_as_float(raw),
                labels=labels,
                type=definition.type,
                help_text=definition.help_text,
            )
        )
    return samples


def _row_mapping(row: Any) -> Any:
    """Named access that works for a SQLAlchemy Row and for a test dict."""
    return getattr(row, "_mapping", row)


async def collect_outbox(*, session_factory: Any = None) -> list[Sample]:
    """The backlog the relay already sees, platform-wide.

    One round trip, no tenant GUC bound: this answers for every tenant at once,
    which is only legitimate because ``outbox_events`` is RLS-exempt (see
    migration ``b2c3d4e5f6a7``) and because NOTHING here is attributable to a
    tenant. A per-tenant breakdown would need a different, authorized surface.

    'failed' counts as backlog on purpose: the relay re-queues a failed row
    after a cool-down, so it is unpublished work, not lost work.
    """
    from sqlalchemy import text as sa_text

    factory = session_factory if session_factory is not None else _default_session_factory()
    sql = sa_text(
        "SELECT count(*) AS n, "
        "       COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at))), 0) AS age "
        "  FROM outbox_events "
        " WHERE status IN ('pending', 'publishing', 'failed')"
    )
    async with factory() as session:
        row = (await session.execute(sql)).first()
    mapping = _row_mapping(row) if row is not None else {}
    pending = int(mapping.get("n") if hasattr(mapping, "get") else mapping["n"])
    age = float(mapping.get("age") if hasattr(mapping, "get") else mapping["age"])
    return [
        Sample(
            name="outbox_pending_total",
            value=pending,
            labels={},
            type="gauge",
            help_text=_BY_NAME["outbox_pending_total"].help_text,
        ),
        Sample(
            name="outbox_oldest_pending_seconds",
            value=round(age, 3),
            labels={},
            type="gauge",
            help_text=_BY_NAME["outbox_oldest_pending_seconds"].help_text,
        ),
    ]


async def collect_dlq(*, redis: Any = None) -> list[Sample]:
    """XLEN per dead-letter stream — O(1) each, the loop ``_dlq_subsystem`` runs.

    Covers EVERY pool stream, which the health surface does not: its tuple
    omits ``campaign_run.events``, so a campaign pool can dead-letter its whole
    audience without moving a single health number.
    """
    client = redis if redis is not None else _default_redis()
    definition = _BY_NAME["dlq_depth"]
    samples: list[Sample] = []
    for stream in POOL_DLQ_STREAMS:
        depth = await client.xlen(stream)
        samples.append(
            Sample(
                name=definition.name,
                value=int(depth or 0),
                labels={"stream": stream},
                type=definition.type,
                help_text=definition.help_text,
            )
        )
    return samples


# ------------------------------------------------------------------- rendering


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels_text(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{_escape(labels[k])}"' for k in sorted(labels))
    return "{" + inner + "}"


def format_samples(samples: Sequence[Sample]) -> str:
    """Prometheus text format 0.0.4: HELP then TYPE then samples, per metric.

    A metric with no samples still gets its HELP/TYPE lines: an absent series
    and a zero series mean different things to an alert rule, and this module
    refuses to let "we could not measure" look like "there is nothing".
    """
    lines: list[str] = []
    by_name: dict[str, list[Sample]] = {}
    for sample in samples:
        by_name.setdefault(sample.name, []).append(sample)
    for definition in CATALOGUE:
        name = definition.name
        rows = by_name.get(name, [])
        lines.append(f"# HELP {name} {definition.help_text}")
        lines.append(f"# TYPE {name} {definition.type}")
        for sample in sorted(rows, key=lambda s: _labels_text(s.labels)):
            if not _NAME_RE.fullmatch(sample.name):
                raise MetricDefinitionError(f"unrenderable metric name {sample.name!r}")
            lines.append(f"{name}{_labels_text(sample.labels)} {sample.value}")
    unexpected = sorted(set(by_name) - {d.name for d in CATALOGUE})
    if unexpected:
        raise MetricDefinitionError(f"samples outside the catalogue: {unexpected}")
    return "\n".join(lines) + "\n"


async def render_prometheus(
    *,
    redis: Any = None,
    session_factory: Any = None,
    include_state: bool = True,
) -> str:
    """One scrape: counters from Redis, gauges from the live stores.

    A collector that raises is recorded in ``metrics_collection_failures_total``
    and reported in THIS body even if Redis is too down to persist it — silence
    is the one outcome a scrape must never produce.
    """
    client = redis if redis is not None else _default_redis()
    samples: list[Sample] = []
    for definition in CATALOGUE:
        if definition.type != "counter":
            continue
        try:
            samples.extend(await _read_counter(definition, client))
        except Exception:  # noqa: BLE001 — fall through to the failure report
            samples = [s for s in samples if s.name != definition.name]

    local_failures: dict[str, int] = {}

    async def _collect(collector: str, fn: Any) -> list[Sample]:
        if not include_state:
            return []
        try:
            return list(await fn())
        except Exception as exc:  # noqa: BLE001
            logger.warning("metrics.collect_failed collector=%s err=%s", collector, exc)
            local_failures[collector] = local_failures.get(collector, 0) + 1
            return []

    samples.extend(
        await _collect("outbox", lambda: collect_outbox(session_factory=session_factory))
    )
    samples.extend(await _collect("dlq", lambda: collect_dlq(redis=client)))

    if local_failures:
        definition = _BY_NAME["metrics_collection_failures_total"]
        persisted = {
            s.labels.get("collector"): float(s.value)
            for s in samples
            if s.name == "metrics_collection_failures_total"
        }
        samples = [
            s for s in samples if s.name != "metrics_collection_failures_total"
        ]
        for collector, count in sorted(local_failures.items()):
            try:
                await increment(
                    "metrics_collection_failures_total",
                    redis=client,
                    strict=False,
                    collector=collector,
                )
            except Exception:  # noqa: BLE001 — best effort; reported below anyway
                pass
            samples.append(
                Sample(
                    name=definition.name,
                    value=max(persisted.get(collector, 0.0), float(count)),
                    labels={"collector": collector},
                    type=definition.type,
                    help_text=definition.help_text,
                )
            )
    return format_samples(samples)


# ---------------------------------------------------------------------- route


def _presents_service_token(authorization: str | None, token: str) -> bool:
    """Constant-time check of ``Authorization: Bearer <token>``.

    Mirrors what ``app.main._RequestIDMiddleware`` accepts from an internal
    caller, reimplemented here rather than imported because core must not
    depend on the composition root. Only the ``Bearer`` keyword is
    case-insensitive, per RFC 9110.
    """
    if not token or not authorization:
        return False
    scheme, _, presented = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(presented, token)


metrics_router = APIRouter(tags=["ops"])


@metrics_router.get("/metrics")
async def expose(request: Request) -> Response:
    """Prometheus exposition, with no tenant context in its signature.

    Mounted at the root beside ``/healthz``: ``/api/v1/**`` is the
    tenant-authenticated surface and a scraper has no JWT to present.
    """
    settings = _settings_for_metrics()
    if settings.is_secure_environment:
        if not settings.service_token_internal:
            return Response(
                content="# metrics_unavailable: SERVICE_TOKEN_INTERNAL is not set\n",
                status_code=503,
                media_type="text/plain; charset=utf-8",
            )
        provided = request.headers.get("authorization")
        if not _presents_service_token(provided, settings.service_token_internal):
            return Response(
                content="# metrics_unavailable: internal service token required\n",
                status_code=401,
                media_type="text/plain; charset=utf-8",
                headers={"WWW-Authenticate": "Bearer"},
            )
    try:
        body = await render_prometheus()
    except Exception as exc:  # noqa: BLE001 — never a 500 with no explanation
        logger.warning("metrics.scrape_failed err=%s", exc)
        return Response(
            content=f"# metrics_unavailable: {type(exc).__name__}\n",
            status_code=503,
            media_type="text/plain; charset=utf-8",
        )
    return Response(content=body, status_code=200, media_type=PROMETHEUS_CONTENT_TYPE)


__all__ = [
    "ALLOWED_LABEL_KEYS",
    "CATALOGUE",
    "EVENT_OUTCOMES",
    "MetricDefinition",
    "MetricDefinitionError",
    "MetricValueError",
    "POOL_DLQ_STREAMS",
    "POOL_STREAMS",
    "PROMETHEUS_CONTENT_TYPE",
    "Sample",
    "collect_dlq",
    "collect_outbox",
    "expose",
    "format_samples",
    "increment",
    "metrics_router",
    "render_prometheus",
]
