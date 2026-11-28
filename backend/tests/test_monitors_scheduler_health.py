"""The sweeps' own alarm: silence is the failure mode nobody reports.

On 26 Nov every recurring job sat in ``scheduled_jobs`` (836 rows, attempts=0,
empty last_error) while the drain died on its first handler. Nothing alerted,
because every monitor watched the storefront and none watched the sweeps.

Two shapes are pinned here, against a fake session so this runs with no DB:

* ``scheduler_jobs_failed`` — rows that used up ``max_attempts``. The drain only
  claims ``queued``/``retrying``, so these never run again: the email, the shift
  close, the reservation expiry they own are silently dead.
* ``scheduler_drain_stalled`` — rows due more than two hours ago and still
  waiting. That is the drain not running at all, which is the outage itself.
"""

from __future__ import annotations

from typing import Any

from app.platform.platform.services import monitors


class _Result:
    def __init__(self, rows: list[Any] | None = None, scalar: int = 0) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one(self) -> int:
        return self._scalar


class _Session:
    """Answers the queries evaluate_monitors makes, in call order."""

    def __init__(self, failed_rows: list[Any], overdue: int) -> None:
        self._failed = failed_rows
        self._overdue = overdue
        self.calls = 0

    async def execute(self, statement: Any) -> _Result:  # noqa: ARG002
        self.calls += 1
        text = str(statement)
        if "scheduled_jobs" not in text:
            # visitor_events window stats: no traffic, nothing to judge.
            return _Result(rows=[], scalar=0)
        if "count" in text and "GROUP BY" in text.upper():
            return _Result(rows=self._failed)
        return _Result(scalar=self._overdue)


async def _alerts(failed_rows: list[Any], overdue: int) -> list[monitors.Alert]:
    return await monitors._scheduler_health(_Session(failed_rows, overdue))  # type: ignore[arg-type]


async def test_a_job_that_used_up_its_attempts_trips_an_alert() -> None:
    alerts = await _alerts([("platform_monitors", 44)], overdue=0)
    codes = [a.code for a in alerts]
    assert codes == ["scheduler_jobs_failed"], codes
    alert = alerts[0]
    assert alert.severity == "critical"
    assert "44" in alert.detail and "platform_monitors" in alert.detail
    # One fingerprint, so five tenants do not become five pages.
    assert alert.fingerprint == "scheduler_jobs_failed"


async def test_jobs_due_hours_ago_mean_the_drain_is_dead() -> None:
    alerts = await _alerts([], overdue=836)
    codes = [a.code for a in alerts]
    assert codes == ["scheduler_drain_stalled"], codes
    assert "836" in alerts[0].detail
    assert alerts[0].fingerprint == "scheduler_drain_stalled"


async def test_a_healthy_drain_is_silent() -> None:
    assert await _alerts([], overdue=0) == []
