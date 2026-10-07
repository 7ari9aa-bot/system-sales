"""Spec §70 — Backup / Disaster Recovery strategy.

Documents and operationalizes the DR strategy:
    - RPO (Recovery Point Objective): 5 minutes (PITR)
    - RTO (Recovery Time Objective): 30 minutes
    - Backup retention: 30 days
    - PITR window: 7 days
    - Restore test schedule: weekly

This is not a backup runner — it is a health-check and documentation
module that ensures the DR strategy is visible, testable, and monitored.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import NotFoundError, ValidationError
from app.core.ids import uuid7
from app.core.model_kit import TimestampMixin

logger = logging.getLogger(__name__)


class RestoreTestStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class DRPolicy(Base, TimestampMixin):
    """§70: the DR policy document, stored as a singleton.

    Makes RPO/RTO/retention visible and auditable rather than implicit.
    """

    __tablename__ = "dr_policy"

    id: Mapped[uuid.UUID] = mapped_column(
        default=uuid7, primary_key=True
    )
    # Recovery Point Objective (minutes of acceptable data loss)
    rpo_minutes: Mapped[int] = mapped_column(server_default="5")
    # Recovery Time Objective (minutes to restore)
    rto_minutes: Mapped[int] = mapped_column(server_default="30")
    # Backup retention (days)
    backup_retention_days: Mapped[int] = mapped_column(server_default="30")
    # PITR window (days)
    pitr_window_days: Mapped[int] = mapped_column(server_default="7")
    # Restore test schedule (cron expression)
    restore_test_cron: Mapped[str] = mapped_column(
        String(63), server_default="0 2 * * 0"  # weekly Sunday 2am
    )
    # Last restore test result — TIMESTAMPTZ in the migration (f9b0c1d2e3f4),
    # so the model must declare timezone=True.
    last_restore_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_restore_test_status: Mapped[str | None] = mapped_column(
        String(15), nullable=True
    )
    # Notes / runbook reference
    runbook_ref: Mapped[str | None] = mapped_column(String(255))


class RestoreTestRun(Base, TimestampMixin):
    """A restore test execution — proves backups work (§70)."""

    __tablename__ = "restore_test_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        default=uuid7, primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(15), server_default="scheduled"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Time to restore (seconds) — compared against RTO
    restore_duration_seconds: Mapped[int | None] = mapped_column(nullable=True)
    # Data loss (seconds) — compared against RPO
    data_loss_seconds: Mapped[int | None] = mapped_column(nullable=True)
    # Checks: {tables_verified, row_counts_matched, rls_policies_checked}
    checks: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    errors: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_restore_tests_status", "status"),
    )


class DRService:
    """§70: DR health checks and restore test orchestration."""

    @staticmethod
    async def get_policy(session: AsyncSession) -> DRPolicy:
        """Get the DR policy (singleton)."""
        policy = (
            await session.execute(select(DRPolicy).limit(1))
        ).scalar_one_or_none()
        if policy is None:
            policy = DRPolicy()
            session.add(policy)
            await session.flush()
        return policy

    @staticmethod
    async def start_restore_test(session: AsyncSession) -> RestoreTestRun:
        """Start a restore test — proves backups are recoverable.

        The run opens in ``running`` with its ``started_at`` stamped, so the
        drill has an auditable beginning even if the completing step dies
        before writing a result (a run stuck in ``running`` is itself visible
        evidence a drill was opened and never closed).
        """
        run = RestoreTestRun(
            status=RestoreTestStatus.RUNNING.value,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        # The actual restore would happen in a worker:
        # 1. Restore latest backup to an isolated DB
        # 2. Verify row counts match
        # 3. Check RLS policies are intact
        # 4. Measure restore time (compare to RTO)
        # 5. Measure data loss (compare to RPO)

        return run

    @staticmethod
    async def complete_restore_test(
        session: AsyncSession,
        run_id: uuid.UUID,
        *,
        passed: bool,
        restore_duration_seconds: int,
        data_loss_seconds: int,
        checks: dict,
        errors: str | None = None,
    ) -> RestoreTestRun:
        """Record the result of a restore test — exactly once.

        The drill is a one-shot state machine: ``running -> passed|failed``.
        Completing a run that is not ``running`` is refused, so a recorded
        result can never be overwritten by a late retry (a falsified audit
        trail is worse than a missing one). The policy's
        ``last_restore_test_*`` stamp is copied from the run's own
        ``completed_at`` — the evidence, not the wall clock of the writer.
        """
        run = (
            await session.execute(
                select(RestoreTestRun).where(RestoreTestRun.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError("restore test run not found")
        if run.status != RestoreTestStatus.RUNNING.value:
            raise ValidationError(
                "restore test run is already completed",
                details={"run_id": str(run_id), "status": run.status},
            )

        run.status = (
            RestoreTestStatus.PASSED.value if passed else RestoreTestStatus.FAILED.value
        )
        run.completed_at = datetime.now(UTC)
        run.restore_duration_seconds = restore_duration_seconds
        run.data_loss_seconds = data_loss_seconds
        run.checks = checks
        run.errors = errors
        await session.flush()

        # Update the policy's last test result with the run's own evidence.
        policy = await DRService.get_policy(session)
        policy.last_restore_test_at = run.completed_at
        policy.last_restore_test_status = run.status
        await session.flush()

        return run

    @staticmethod
    async def check_dr_health(session: AsyncSession) -> dict:
        """Return DR health summary for the global health indicator (§103).

        Every field here is derived from RECORDED DRILL EVIDENCE — the last
        ``RestoreTestRun`` result stamped onto the policy — never from a
        configured intent. ``healthy`` requires the last drill to have
        actually PASSED and to be inside its weekly window; a drill that
        never ran is ``overdue``, and a passed-but-stale drill is overdue
        too, because "we tested it once, last quarter" is not recovery
        capability.
        """
        policy = await DRService.get_policy(session)

        # Check if restore test is overdue
        overdue = False
        if policy.last_restore_test_at:
            # Should have run within the restore_test_cron schedule
            next_expected = policy.last_restore_test_at + timedelta(days=7)
            overdue = datetime.now(UTC) > next_expected
        else:
            overdue = True  # never tested

        return {
            "rpo_minutes": policy.rpo_minutes,
            "rto_minutes": policy.rto_minutes,
            "last_restore_test": policy.last_restore_test_at.isoformat()
            if policy.last_restore_test_at
            else None,
            "last_restore_status": policy.last_restore_test_status,
            "restore_test_overdue": overdue,
            "healthy": not overdue and policy.last_restore_test_status == "passed",
        }
