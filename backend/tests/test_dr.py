"""The §70 DR drill cycle and the diagnostics engine's fail-closed contract.

Two halves of one promise — recovery decisions are made from EVIDENCE, and
the evidence machinery itself cannot lie:

1. DR drill (``app/modules/platform/dr.py``): start → execute → result →
   the policy's last-test stamp on the same row, with ``check_dr_health``
   deriving every answer from that recorded evidence. A drill that never
   ran, a drill that failed, and a drill that went stale must all read as
   UNHEALTHY — a configured RPO/RTO is intent, not capability.

2. Diagnostics (``app/modules/platform/diagnostics.py``): every check runs
   a live probe, carries its evidence, and — the part these tests pin —
   reports a check that CANNOT run as a ``degraded``/``down`` finding with
   the error attached. An anti-silent-failure engine that renders its own
   outage as "healthy" is the worst silent failure of all.

The DR drills run against real PostgreSQL through the transactional ``db``
fixture (rolled back); the diagnostics checks are DB-free fakes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.errors import NotFoundError, ValidationError
from app.modules.platform import diagnostics as diag
from app.modules.platform.diagnostics import SystemDiagnosticsService
from app.modules.platform.dr import DRService

# ----------------------------------------------------------------- DR drill


_DRILL_CHECKS = {"tables_verified": 12, "row_counts_matched": True, "rls_policies_checked": 4}


async def test_drill_cycle_is_auditable_start_to_finish(db) -> None:
    """start → complete → the policy row stamps THIS run's evidence."""
    run = await DRService.start_restore_test(db)
    assert run.status == "running"
    assert run.started_at is not None

    run = await DRService.complete_restore_test(
        db,
        run.id,
        passed=True,
        restore_duration_seconds=120,
        data_loss_seconds=15,
        checks=dict(_DRILL_CHECKS),
    )

    assert run.status == "passed"
    assert run.completed_at is not None
    assert run.restore_duration_seconds == 120
    assert run.data_loss_seconds == 15
    assert run.checks == _DRILL_CHECKS

    # The policy singleton carries the run's OWN stamp — the evidence of the
    # drill that produced it, not the wall clock of whoever wrote the row.
    policy = await DRService.get_policy(db)
    assert policy.last_restore_test_status == "passed"
    assert policy.last_restore_test_at == run.completed_at

    health = await DRService.check_dr_health(db)
    assert health["healthy"] is True
    assert health["restore_test_overdue"] is False
    assert health["last_restore_status"] == "passed"
    assert health["rpo_minutes"] == policy.rpo_minutes
    assert health["rto_minutes"] == policy.rto_minutes


async def test_a_failed_drill_reports_unhealthy(db) -> None:
    """A drill that RAN and FAILED is evidence of missing recovery capability."""
    run = await DRService.start_restore_test(db)
    run = await DRService.complete_restore_test(
        db,
        run.id,
        passed=False,
        restore_duration_seconds=600,
        data_loss_seconds=900,
        checks={"tables_verified": 3, "row_counts_matched": False},
        errors="row counts diverged on outbox_events",
    )

    assert run.status == "failed"

    health = await DRService.check_dr_health(db)
    assert health["healthy"] is False
    assert health["last_restore_status"] == "failed"
    assert health["restore_test_overdue"] is False  # fresh, but failed


async def test_health_demands_a_recent_pass_not_a_configured_intent(db) -> None:
    """Stale or never-run drills are overdue — intent is not capability."""
    # A pass from 8 days ago is outside the weekly window.
    run = await DRService.start_restore_test(db)
    await DRService.complete_restore_test(
        db,
        run.id,
        passed=True,
        restore_duration_seconds=60,
        data_loss_seconds=0,
        checks=dict(_DRILL_CHECKS),
    )
    policy = await DRService.get_policy(db)
    policy.last_restore_test_at = datetime.now(UTC) - timedelta(days=8)
    await db.flush()

    health = await DRService.check_dr_health(db)
    assert health["restore_test_overdue"] is True
    assert health["healthy"] is False

    # A policy that has never been drilled is overdue by definition.
    policy.last_restore_test_at = None
    policy.last_restore_test_status = None
    await db.flush()

    health = await DRService.check_dr_health(db)
    assert health["restore_test_overdue"] is True
    assert health["healthy"] is False
    assert health["last_restore_test"] is None


async def test_a_completed_drill_cannot_be_overwritten(db) -> None:
    """Fail-first: the pre-fix implementation accepted a second completion and
    OVERWROTE the recorded result — a late retry could falsify the audit trail
    of the one control that proves backups work. The drill is one-shot."""
    run = await DRService.start_restore_test(db)
    run = await DRService.complete_restore_test(
        db,
        run.id,
        passed=True,
        restore_duration_seconds=90,
        data_loss_seconds=0,
        checks=dict(_DRILL_CHECKS),
    )
    original_status = run.status
    original_completed_at = run.completed_at
    original_checks = dict(run.checks)

    with pytest.raises(ValidationError, match="already completed"):
        await DRService.complete_restore_test(
            db,
            run.id,
            passed=False,
            restore_duration_seconds=1,
            data_loss_seconds=1,
            checks={},
            errors="retry after the fact",
        )

    await db.refresh(run)
    assert run.status == original_status
    assert run.completed_at == original_completed_at
    assert run.checks == original_checks
    # And the policy stamp still says what the drill actually concluded.
    policy = await DRService.get_policy(db)
    assert policy.last_restore_test_status == "passed"


async def test_completing_an_unknown_run_is_a_404_not_a_bare_valueerror(db) -> None:
    """The unified error contract: a missing run answers NotFoundError so the
    error envelope (and any future route) speaks 404, not a raw ValueError."""
    with pytest.raises(NotFoundError):
        await DRService.complete_restore_test(
            db,
            uuid.uuid4(),
            passed=True,
            restore_duration_seconds=1,
            data_loss_seconds=1,
            checks={},
        )


# ----------------------------------------------------------------- diagnostics


class _RaisingSession:
    """A session whose probes all fail — the network-outage stand-in."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("connection reset by peer")


class _FailingRedis:
    """A Redis client where every operation errors out."""

    async def ping(self) -> None:
        raise RuntimeError("redis is down")

    async def xlen(self, _stream: str) -> int:
        raise RuntimeError("redis is down")


async def test_a_database_outage_is_a_finding_not_an_exception() -> None:
    """check_database probes live and turns the outage into evidence."""
    finding = await SystemDiagnosticsService.check_database(_RaisingSession())

    assert finding["status"] == "down"
    assert "RuntimeError" in (finding["error"] or "")
    assert finding["root_cause"] and finding["remediation"]


async def test_a_redis_outage_is_a_finding_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diag, "get_redis", lambda: _FailingRedis())

    finding = await SystemDiagnosticsService.check_redis()

    assert finding["status"] == "down"
    assert "RuntimeError" in (finding["error"] or "")
    assert finding["root_cause"] and finding["remediation"]


async def test_a_broken_integrity_probe_is_degraded_never_healthy() -> None:
    """Fail-first: the pre-fix except branch reported status "healthy" with no
    error — a broken invariant query read as "no anomalies detected", the
    exact silent failure this engine exists to surface."""
    finding = await SystemDiagnosticsService.check_data_integrity(_RaisingSession(), uuid.uuid4())

    assert finding["status"] == "degraded"
    assert "RuntimeError" in (finding["error"] or "")
    assert finding["root_cause"] and finding["remediation"]


async def test_a_redis_outage_cannot_certify_the_dlq_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-first: the pre-fix loop swallowed every XLEN error, so a Redis
    outage reported ``healthy`` with ``dlq_depth: 0`` — the queue was
    certified unseen. An unreadable DLQ must degrade with evidence."""
    monkeypatch.setattr(diag, "get_redis", lambda: _FailingRedis())

    finding = await SystemDiagnosticsService.check_dead_letter_queue()

    assert finding["status"] == "degraded"
    assert finding["error"], "an unreadable DLQ must carry the reason"
    assert finding["metrics"].get("unreadable_streams", 0) > 0
    assert finding["root_cause"] and finding["remediation"]


async def test_the_dlq_check_reads_the_streams_the_workers_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-first: the pre-hardening inventory probed phantom stream names
    nothing writes to (``stream:dlq``...), so the check could never observe a
    real backlog. It must read the canonical §103 inventory instead."""
    probed: list[str] = []

    class _RecordingRedis:
        async def ping(self) -> None:
            return None

        async def xlen(self, stream: str) -> int:
            probed.append(stream)
            # One canonical stream actually carries dead letters.
            return 7 if stream == "message.events.dlq" else 0

    monkeypatch.setattr(diag, "get_redis", lambda: _RecordingRedis())

    finding = await SystemDiagnosticsService.check_dead_letter_queue()

    assert probed, "the DLQ check must probe real streams"
    assert "message.events.dlq" in probed
    assert not any(name.startswith("stream:") for name in probed), (
        f"probing phantom stream names nobody writes to: {probed}"
    )
    assert finding["status"] == "degraded"
    assert finding["metrics"]["dlq_depth"] == 7
