"""A failed template resync leaves a mark the owner can see (M11).

It used to be a log line and nothing else: the store's templates stayed at whatever Meta last said
and the only trace was a warning nobody reads. The mark rides `webhook_health`, which
`check_integrations` already reports; only a resync that SUCCEEDS clears it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.applications.apparel.modules.conversations.gateway.ingest import _record_template_resync
from app.modules.platform.diagnostics import channel_problems

TENANT = uuid.uuid4()


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Session:
    def __init__(self, integration, *, fail_on_execute: bool = False):
        self._integration = integration
        self._fail = fail_on_execute
        self.flushed = 0

    async def execute(self, _stmt):
        if self._fail:
            raise ConnectionError("db went away")
        return _Result(self._integration)

    async def flush(self):
        self.flushed += 1


def _integration(health=None):
    return SimpleNamespace(webhook_health=health)


async def test_a_failed_resync_is_recorded_on_the_channel():
    row = _integration({"consecutive_failures": 0})
    session = _Session(row)

    await _record_template_resync(session, TENANT, "whatsapp", error="TimeoutError")

    assert row.webhook_health["template_resync_error"] == "TimeoutError"
    assert row.webhook_health["template_resync_failed_at"]
    assert row.webhook_health["consecutive_failures"] == 0  # other health facts survive
    assert session.flushed == 1


async def test_a_long_error_name_is_truncated():
    row = _integration({})
    await _record_template_resync(_Session(row), TENANT, "whatsapp", error="X" * 500)

    assert len(row.webhook_health["template_resync_error"]) == 120


async def test_a_successful_resync_clears_the_mark_and_stamps_when():
    row = _integration(
        {"template_resync_error": "TimeoutError", "template_resync_failed_at": "2026-01-01"}
    )

    await _record_template_resync(_Session(row), TENANT, "whatsapp", error=None)

    assert "template_resync_error" not in row.webhook_health
    assert "template_resync_failed_at" not in row.webhook_health
    assert row.webhook_health["template_resync_ok_at"]


async def test_a_successful_resync_with_no_mark_writes_nothing():
    """The common case runs on every delivery; it must not churn the row."""
    row = _integration({"consecutive_failures": 0})
    session = _Session(row)

    await _record_template_resync(session, TENANT, "whatsapp", error=None)

    assert row.webhook_health == {"consecutive_failures": 0}
    assert session.flushed == 0


async def test_a_channel_with_no_integration_row_is_left_alone():
    session = _Session(None)
    await _record_template_resync(session, TENANT, "whatsapp", error="TimeoutError")
    assert session.flushed == 0


async def test_a_mark_that_cannot_be_written_never_fails_the_delivery():
    await _record_template_resync(
        _Session(_integration({}), fail_on_execute=True), TENANT, "whatsapp", error="X"
    )  # must not raise


def test_a_channel_with_a_failed_resync_is_reported_as_a_problem():
    rows = [("whatsapp", "active", {"template_resync_error": "TimeoutError"})]

    problems = channel_problems(rows)

    assert len(problems) == 1
    assert problems[0]["provider"] == "whatsapp"
    assert "TimeoutError" in str(problems[0])


def test_a_healthy_channel_is_not_reported():
    assert channel_problems([("whatsapp", "active", {"consecutive_failures": 0})]) == []


def test_a_cleared_mark_stops_the_report():
    assert channel_problems([("whatsapp", "active", {"template_resync_ok_at": "now"})]) == []
