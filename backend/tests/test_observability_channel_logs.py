"""The lines an operator greps when a channel breaks are structured, and failed requests count.

Most log lines are written through the standard library (`logger.warning("meta_oauth...")`). They
went out as bare text: no level, no time, no request id, and not JSON beside the structlog lines
around them (M5). And `request_failed` was only a log line, so nothing could alert on a rising
rate of them (M16).
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from app.core import metrics, observability
from app.core.errors import request_id_contextvar
from app.core.log_redaction import RedactSecretsFilter


@pytest.fixture
def captured(monkeypatch):
    """Run configure_logging against a private root handler and return what it prints."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    for handler in list(root.handlers):
        root.removeHandler(handler)

    lines: list[str] = []

    class _Sink(logging.StreamHandler):
        def emit(self, record):
            lines.append(self.format(record))

    sink = _Sink()
    root.addHandler(sink)
    # basicConfig is a no-op once a handler exists, so configure_logging reuses ours and leaves the
    # root level alone: set it as a running server would have it.
    root.setLevel(logging.INFO)
    observability.configure_logging()
    token = request_id_contextvar.set("req-test-1")
    try:
        yield lines, sink
    finally:
        request_id_contextvar.reset(token)
        root.removeHandler(sink)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
        structlog.reset_defaults()


def test_a_standard_library_line_is_json_with_level_time_and_request_id(captured):
    lines, _ = captured
    logging.getLogger("app.applications.apparel.modules.customers.meta_oauth").warning("meta_oauth.link_failed")

    entry = json.loads(lines[-1])
    assert entry["event"] == "meta_oauth.link_failed"
    assert entry["level"] == "warning"
    assert entry["logger"] == "app.applications.apparel.modules.customers.meta_oauth"
    assert entry["request_id"] == "req-test-1"
    assert entry["timestamp"].endswith("Z")


def test_a_secret_in_a_standard_library_line_is_still_redacted(captured):
    lines, _ = captured
    logging.getLogger("app.x").warning("graph call failed access_token=EAAB1234567890123456789012")

    assert "EAAB1234567890123456789012" not in lines[-1]
    assert "[REDACTED]" in lines[-1]
    json.loads(lines[-1])


def test_the_redaction_filter_is_still_on_the_handler(captured):
    _, sink = captured
    assert any(isinstance(f, RedactSecretsFilter) for f in sink.filters)


def test_an_exception_keeps_its_traceback_in_the_json(captured):
    lines, _ = captured
    try:
        _ = 1 / 0
    except ZeroDivisionError:
        logging.getLogger("app.x").exception("it broke")

    entry = json.loads(lines[-1])
    assert "ZeroDivisionError" in entry["exception"]


def test_a_structlog_line_still_works_and_carries_the_same_keys(capsys, captured):
    observability.get_logger("http").info("request", status=200)

    out = capsys.readouterr().out.strip().splitlines()[-1]
    entry = json.loads(out)
    assert entry["event"] == "request"
    assert entry["status"] == 200
    assert entry["level"] == "info"
    assert entry["request_id"] == "req-test-1"


def test_a_line_that_already_names_its_request_id_keeps_it(capsys, captured):
    observability.get_logger("http").info("request", request_id="explicit-9")

    entry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert entry["request_id"] == "explicit-9"


def test_no_request_id_is_invented_outside_a_request(captured):
    lines, _ = captured
    request_id_contextvar.set(None)
    logging.getLogger("app.x").info("startup")

    assert "request_id" not in json.loads(lines[-1])


# ---- M16: a failed request is counted ----
def test_the_failed_request_counter_is_declared_without_labels():
    definition = next(m for m in metrics.CATALOGUE if m.name == "http_requests_failed_total")
    assert definition.type == "counter"
    assert definition.label_names == ()  # a path carries ids; aggregates only


async def test_counting_a_failed_request_increments_the_counter(monkeypatch):
    seen = []

    async def fake_increment(name, **kwargs):
        seen.append((name, kwargs))

    monkeypatch.setattr(metrics, "increment", fake_increment)
    await observability._count_failed_request()

    assert seen == [("http_requests_failed_total", {"strict": False})]


async def test_a_metrics_outage_never_makes_a_failed_request_worse(monkeypatch):
    async def broken(name, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(metrics, "increment", broken)
    await observability._count_failed_request()  # must not raise
