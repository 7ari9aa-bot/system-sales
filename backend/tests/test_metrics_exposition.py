"""O10: ``/metrics`` — a Prometheus exposition of what this codebase already knows.

Verified against the tree before writing anything: ``app/modules/platform``
answers ``GET /platform/metrics`` from the *business* metric registry (revenue,
ROAS…), and there is no operational exposition anywhere — ``prometheus`` appears
in zero files in the repo, and ``prometheus_client`` is not a dependency. So
this is a hand-rolled text-format renderer, which for these five series is the
honest minimum rather than a new runtime dependency.

Only signals that ALREADY exist are exposed. Everything here is either (a) a
log event the worker runtime already emits and now also counts, or (b) an
aggregate the health surface already computes. Nothing is invented:

    outbox_pending_total              <- _outbox_subsystem's backlog, un-scoped
    outbox_oldest_pending_seconds     <- the same min(created_at) query
    dlq_depth{stream}                 <- _dlq_subsystem's XLEN loop
    worker_events_total{stream,outcome}<- worker.deferred / .handle_failed /
                                          .permanent_failure / .idempotent_skip /
                                          .inbox_contended
    worker_seconds_total{stream}      <- the §144 charge _charge_worker_seconds
                                         already computes

THE EXPOSURE RULE, and why it can be this shape
-----------------------------------------------
``outbox_events`` and ``idempotency_keys`` are on the ``_RLS_EXEMPT`` list in
migration ``b2c3d4e5f6a7`` — the runtime role can read them across tenants
precisely so the relay works. That is what makes a global backlog number
computable at all, and it is also the leak: an endpoint readable by anyone can
see platform-wide state. Two properties contain it, both pinned below:

1. **Aggregates only.** The catalogue declares its label names in one place, and
   every label key must be on a closed allow-list. ``tenant_id`` / ``user_id`` /
   ``customer_id`` / ``workspace_id`` / ``location_id`` / ``aggregate_id`` /
   ``correlation_id`` are not labels and cannot become one without a code change
   here — a per-tenant series is the leak, not the aggregate.
2. **Scrape values are shape-checked.** A label value must match
   ``[A-Za-z0-9_.:/-]{1,64}``, so a value that happens to BE an identifier
   (a UUID tenant id, an email, a phone) is refused at the call site even if
   someone adds a label name the allow-list later forgives.

Plus the route itself: no tenant context (it has no dependency on one), and in
any environment where RLS/secret checks are enforced it requires the internal
service token — unauthenticated counts are a local/dev convenience, not a
production surface.
"""

from __future__ import annotations

import inspect
import re

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import metrics
from app.main import create_app

# --------------------------------------------------------------- the catalogue


def test_the_catalogue_declares_no_tenant_bearing_label() -> None:
    """The exposure rule, part 1: the series set is aggregate by construction.

    Reading the catalogue rather than the rendered text is what makes this a
    gate: a new metric added with a ``tenant_id`` label fails here even though
    nothing calls it yet.
    """
    forbidden = {
        "tenant_id",
        "tenant",
        "user_id",
        "user",
        "customer_id",
        "customer",
        "workspace_id",
        "location_id",
        "aggregate_id",
        "correlation_id",
        "request_id",
        "email",
        "phone",
        "ip",
        "path",
    }
    offenders: dict[str, set[str]] = {}
    for metric_def in metrics.CATALOGUE:
        bad = set(metric_def.label_names) & forbidden
        if bad:
            offenders[metric_def.name] = bad
    assert not offenders, f"tenant-identifiable labels in the catalogue: {offenders}"

    # And the allow-list must not be decorative: every declared label key is on it.
    assert set(metrics.ALLOWED_LABEL_KEYS) >= {
        key for m in metrics.CATALOGUE for key in m.label_names
    }, "a catalogue entry uses a label key the allow-list does not carry"


def test_the_catalogue_carries_the_five_signals_and_nothing_invented() -> None:
    """The five O10 asks for, minus the two this tree cannot back.

    ``rate_limit_rejections`` and ``idempotency_conflicts`` are deliberately
    ABSENT: the only code that sees those outcomes lives in
    ``app/core/middleware.py`` and ``app/core/idempotency.py``, neither of which
    this lane may edit, and nothing persists the rejection today. Publishing a
    series that can only ever read zero is fake-green, so the catalogue asserts
    its own honesty instead.
    """
    names = {m.name for m in metrics.CATALOGUE}
    assert names == {
        "outbox_pending_total",
        "outbox_oldest_pending_seconds",
        "dlq_depth",
        "worker_events_total",
        "worker_seconds_total",
        "metrics_collection_failures_total",
    }, names

    # The two series the register names but this tree cannot back must not be
    # here — this assertion fails the moment someone adds a zero-valued stub.
    for unbaked in ("rate_limit_rejections_total", "idempotency_conflicts_total"):
        assert unbaked not in names, f"{unbaked} has no increment site in this tree"


# ------------------------------------------------------------- label hygiene


async def test_an_unlisted_label_key_is_refused_rather_than_silently_stored() -> None:
    """A typo'd label must not become a series nobody scrapes."""
    with pytest.raises(metrics.MetricDefinitionError):
        await metrics.increment("worker_events_total", tenant_id="x", outcome="processed")


async def test_a_label_value_that_could_be_an_identifier_is_refused() -> None:
    """The second half of the exposure rule: values are shape-checked.

    ``stream=11111111-1111-1111-1111-111111111111`` is a tenant id wearing a
    legal label name. Refusing the SHAPE is what stops that being a leak with a
    different field name on it.
    """
    with pytest.raises(metrics.MetricValueError):
        await metrics.increment(
            "worker_events_total",
            stream="11111111-1111-1111-1111-111111111111",
            outcome="processed",
        )
    with pytest.raises(metrics.MetricValueError):
        await metrics.increment("worker_events_total", stream="a" * 200, outcome="processed")
    with pytest.raises(metrics.MetricValueError):
        await metrics.increment("worker_events_total", stream="us er@x", outcome="processed")


async def test_an_unknown_outcome_is_refused() -> None:
    """``outcome`` is a closed set: an open one is how a label cardinality bomb
    gets shipped inside a worker that logs the failing tenant's id."""
    with pytest.raises(metrics.MetricValueError):
        await metrics.increment("worker_events_total", stream="message.events", outcome="nonsense")


async def test_an_unknown_metric_name_is_refused() -> None:
    with pytest.raises(metrics.MetricDefinitionError):
        await metrics.increment("not_in_the_catalogue")


# ------------------------------------------------------------------ counting


async def test_increments_accumulate_in_the_shared_store() -> None:
    """The counters live in Redis, not in the process.

    Workers and API are different processes, so an in-memory registry would put
    the worker numbers where the scraper cannot reach them. (Same reason
    ``app.core.fairness`` keeps its budget counters in Redis.)
    """
    fake = FakeRedis(decode_responses=True)
    await metrics.increment(
        "worker_events_total", redis=fake, stream="message.events", outcome="processed"
    )
    await metrics.increment(
        "worker_events_total",
        redis=fake,
        stream="message.events",
        outcome="processed",
        value=4,
    )
    body = await metrics.render_prometheus(redis=fake)
    assert 'worker_events_total{outcome="processed",stream="message.events"} 5' in body


async def test_a_counter_written_in_one_process_reads_in_another() -> None:
    """The whole reason the counters are in Redis and not in a dict.

    Two ``FakeRedis`` clients over one ``FakeServer`` stand in for the worker
    process that writes and the API process that renders; a shared keyspace is
    exactly what an in-process registry cannot give.
    """
    from fakeredis import FakeServer

    server = FakeServer()
    writer = FakeRedis(decode_responses=True, server=server)
    reader = FakeRedis(decode_responses=True, server=server)

    await metrics.increment(
        "worker_seconds_total", stream="webhook.events", value=7, redis=writer
    )
    body = await metrics.render_prometheus(redis=reader)
    assert 'worker_seconds_total{stream="webhook.events"} 7' in body


async def test_a_redis_outage_never_raises_out_of_a_worker_increment() -> None:
    """Counting must not be able to take a pool down."""

    class _Dead:
        async def hincrbyfloat(self, *a, **kw):
            raise ConnectionError("redis is down")

        def pipeline(self):  # pragma: no cover
            raise ConnectionError("redis is down")

    # `strict=False` is the call shape the worker runtime uses.
    await metrics.increment(
        "worker_events_total",
        redis=_Dead(),
        stream="message.events",
        outcome="retried",
        strict=False,
    )


async def test_strict_mode_is_the_default_so_a_misuse_still_fails_loudly() -> None:
    class _Dead:
        async def hincrbyfloat(self, *a, **kw):
            raise ConnectionError("redis is down")

    # No `strict` argument: this is the half that pins the DEFAULT, so passing it
    # here would test the parameter instead of the default. Labels are the legal
    # shape because the point is what happens at REDIS, after validation passed.
    with pytest.raises(ConnectionError):
        await metrics.increment(
            "worker_events_total", redis=_Dead(), stream="message.events", outcome="processed"
        )


# ------------------------------------------------------------------- rendering


async def test_the_body_is_valid_prometheus_text_format() -> None:
    fake = FakeRedis(decode_responses=True)
    await metrics.increment(
        "worker_events_total", redis=fake, stream="message.events", outcome="processed"
    )
    body = await metrics.render_prometheus(redis=fake)

    lines = body.splitlines()
    # Every series gets a HELP and a TYPE line before its samples.
    for name in ("worker_events_total", "worker_seconds_total"):
        assert any(line.startswith(f"# HELP {name} ") for line in lines), f"no HELP for {name}"
        assert any(line.startswith(f"# TYPE {name} ") for line in lines), f"no TYPE for {name}"
    for line in lines:
        assert not line.startswith("#") or re.match(
            r"^# (HELP|TYPE) [a-zA-Z_:][a-zA-Z0-9_:]* ", line
        ), f"malformed comment line: {line!r}"
        if line and not line.startswith("#"):
            assert re.match(r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^{}]*\})? [0-9eE.+-]+$", line), line


async def test_label_values_are_escaped() -> None:
    samples = [
        metrics.Sample(
            name="dlq_depth",
            value=1,
            labels={"stream": 'we"ird\\stream'},
            type="gauge",
            help_text="x",
        )
    ]
    body = metrics.format_samples(samples)
    assert r'dlq_depth{stream="we\"ird\\stream"} 1' in body


async def test_the_output_ends_with_a_newline_and_no_trailing_blank_lines() -> None:
    fake = FakeRedis(decode_responses=True)
    body = await metrics.render_prometheus(redis=fake)
    assert body.endswith("\n")
    assert "\n\n" not in body


# ------------------------------------------------------- the state collectors


class _ScalarResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    """Answers the one backlog query the collector makes."""

    def __init__(self, row):
        self._row = row
        self.sql: list[str] = []

    async def execute(self, statement, params=None):
        self.sql.append(str(statement))
        return _ScalarResult(self._row)

    async def close(self) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


async def test_the_outbox_collector_reads_the_backlog_the_relay_already_sees() -> None:
    """No new instrument: the same min(created_at) the health surface uses.

    It must NOT bind a tenant GUC — a per-tenant backlog is both the leak and
    wrong for a platform gauge, and the query works because outbox_events is
    RLS-exempt.
    """
    session = _FakeSession({"n": 12, "age": 45.5})
    samples = await metrics.collect_outbox(session_factory=_FakeSessionFactory(session))
    by_name = {s.name: s for s in samples}
    assert by_name["outbox_pending_total"].value == 12
    assert by_name["outbox_oldest_pending_seconds"].value == 45.5
    joined = " ".join(session.sql).lower()
    assert "app.tenant_id" not in joined, "the backlog collector bound a tenant"
    assert "set_config" not in joined


async def test_the_dlq_collector_covers_every_pool_stream_not_just_the_four_health_checks() -> None:
    """``_dlq_subsystem`` loops a hand-written 4-stream tuple and so never counts
    ``campaign_run.events.dlq`` — the campaign pool dead-letters into a stream
    nothing reads. The exposition covers every declared pool stream."""
    fake = FakeRedis(decode_responses=True)
    for i in range(3):
        await fake.xadd("campaign_run.events.dlq", {"id": f"e{i}", "payload": "{}", "meta": "{}"})
    samples = await metrics.collect_dlq(redis=fake)
    streams = {s.labels["stream"]: s.value for s in samples}
    assert streams.get("campaign_run.events.dlq") == 3, (
        f"campaign DLQ missing from the exposition: {streams}"
    )
    for declared in metrics.POOL_DLQ_STREAMS:
        assert declared in streams, f"{declared} has no series"


async def test_a_broken_collector_reports_itself_instead_of_vanishing() -> None:
    """A missing series must not look like a healthy zero."""

    class _Exploding:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise RuntimeError("db unreachable")

        async def __aexit__(self, *exc):
            return False

    fake = FakeRedis(decode_responses=True)
    body = await metrics.render_prometheus(
        redis=fake, session_factory=_Exploding()
    )
    assert 'metrics_collection_failures_total{collector="outbox"}' in body
    # The promise is that a failed collector publishes NO NUMBERS, not that its
    # metric disappears: the HELP/TYPE preamble is rendered from the catalogue, so
    # matching the whole body would fail on a comment line and hide the real rule.
    samples = [line for line in body.splitlines() if line and not line.startswith("#")]
    assert not any(line.startswith("outbox_pending_total") for line in samples), samples


# ----------------------------------------------------------------- the route


@pytest.fixture
def route_backends(monkeypatch: pytest.MonkeyPatch):
    """Point the route's two collectors at fakes.

    Without this the handler would dial a real Redis/Postgres, which is what
    every other test in this file avoids by passing its own backends.
    """
    fake = FakeRedis(decode_responses=True)
    session = _FakeSession({"n": 0, "age": None})
    monkeypatch.setattr(metrics, "_default_redis", lambda: fake)
    monkeypatch.setattr(
        metrics, "_default_session_factory", lambda: _FakeSessionFactory(session)
    )
    return fake


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(metrics.metrics_router)
    return app


def _flat_routes(node) -> list:
    """Every concrete route under a router, through FastAPI 0.141's indirection.

    ``include_router`` now defers to an ``_IncludedRouter`` with neither
    ``.routes`` nor ``.path`` — the included router hangs off
    ``include_context.included_router`` (the same shape
    ``tests/test_route_parameter_declarations.py`` documents and walks). Reading
    ``app.routes`` flat would see one pathless object and conclude the route does
    not exist.
    """
    found: list = []
    context = getattr(node, "include_context", None)
    child = getattr(context, "included_router", None) if context is not None else None
    if child is not None:
        found.extend(_flat_routes(child))
    if getattr(node, "path", None) is not None:
        found.append(node)
    for sub in getattr(node, "routes", None) or []:
        found.extend(_flat_routes(sub))
    return found


def test_the_route_takes_no_tenant_context_at_all() -> None:
    """`/metrics` must not be reachable only by a tenant, and must not need one.

    Asserted structurally: the handler's only parameter is the request, and it
    carries no FastAPI dependencies. A route that resolved a TenantContext
    would either 401 scrapes or leak one tenant's numbers to another.
    """
    routes = [r for r in _flat_routes(_app()) if getattr(r, "path", "") == "/metrics"]
    assert len(routes) == 1
    endpoint = routes[0].endpoint
    params = list(inspect.signature(endpoint).parameters)
    assert params == ["request"], params
    assert not routes[0].dependencies
    # No parameter annotated with anything tenant-shaped.
    for name, param in inspect.signature(endpoint).parameters.items():
        assert "tenant" not in str(param.annotation).lower(), name


def test_a_scrape_in_a_development_environment_needs_no_credential(
    route_backends,
) -> None:
    """Local/dev: unauthenticated, like /healthz already is."""
    client = TestClient(_app())
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    assert "outbox_pending_total" in response.text
    assert "dlq_depth" in response.text


def test_the_route_is_mounted_at_the_root_not_under_a_tenant_scoped_prefix() -> None:
    """`/api/v1/...` is where tenant-authenticated surface lives; a scrape
    target has to sit beside /healthz.

    Asserted against ``create_app()`` rather than a private app, because the
    mounting is the thing under test: a route defined and never included answers
    404 to a scraper forever.
    """
    paths = {getattr(r, "path", "") for r in _flat_routes(create_app())}
    assert "/metrics" in paths
    assert "/healthz" in paths, "the probe it is supposed to sit beside"
    assert not any(p.startswith("/api/v1/metrics") for p in paths)


def test_a_scrape_in_a_secure_environment_without_a_token_is_refused(
    route_backends,
) -> None:
    """The leak this lane is judged on.

    Platform-wide backlog and DLQ counts say things about a tenant's volume the
    moment they are time-series-able: a sustained ``dlq_depth`` step is a
    customer, and ``outbox_pending_total`` growth is a busy tenant's business.
    In every environment where the rest of the config is enforced, the scrape
    must present the internal service token.
    """
    client = TestClient(_app())
    with _secure_environment():
        response = client.get("/metrics")
    assert response.status_code == 401, response.text


def test_a_secure_scrape_with_the_service_token_is_served(route_backends) -> None:
    client = TestClient(_app())
    with _secure_environment(token="s3cret-token"):
        ok = client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
        bad = client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert ok.status_code == 200, ok.text
    assert bad.status_code == 401, bad.text


def test_a_secure_environment_with_no_token_configured_serves_nothing(
    route_backends,
) -> None:
    """Fail CLOSED: an unset token must not degrade into an open endpoint."""
    client = TestClient(_app())
    with _secure_environment(token=""):
        response = client.get("/metrics")
    assert response.status_code == 503, response.text


# ---------------------------------------------------------------- helpers


class _secure_environment:
    """Force ``is_secure_environment`` at the seam the route reads settings through.

    The route goes through ``_settings_for_metrics`` rather than calling
    ``get_settings()`` inline for exactly this reason: flipping ``ENVIRONMENT``
    would trip ``_refuse_insecure_configuration`` for every later test that
    builds Settings, and clearing the lru_cache from a context manager leaks
    across test boundaries.
    """

    def __init__(self, token: str = "unit-test-token"):
        self.token = token

    def __enter__(self):
        self._real = metrics._settings_for_metrics
        metrics._settings_for_metrics = lambda: _StubSettings(secure=True, token=self.token)
        return self

    def __exit__(self, *exc):
        metrics._settings_for_metrics = self._real
        return False


class _StubSettings:
    def __init__(self, *, secure: bool, token: str):
        self.is_secure_environment = secure
        self.service_token_internal = token
