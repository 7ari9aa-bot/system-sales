"""Spec §56 — Partitioning strategy.

For high-volume tables (Messages, AuditLog, AIUsage, EventLog,
WebhookEvent), PostgreSQL declarative partitioning by created_at (range,
monthly) is used. tenant_id is always indexed on each partition.

§56: "Do not create thousands of partitions due to tenant count."
We partition by time, not by tenant.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Tables eligible for range partitioning by created_at (§56)
PARTITION_CANDIDATES = frozenset({
    "messages",
    "audit_logs",
    "ai_usage",
    "event_log",
    "webhook_events",
    "delivery_attempts",
    "outbound_messages",
})


class PartitionManager:
    """§56: create and manage monthly partitions for high-volume tables.

    Partitions are created ahead of time (next month's partition is
    created before the month starts) so inserts never fail due to a
    missing partition.
    """

    @staticmethod
    async def ensure_partition(
        session: AsyncSession,
        table_name: str,
        *,
        year: int,
        month: int,
    ) -> bool:
        """Create a monthly partition if it does not exist.

        Returns True if created, False if already existed.
        """
        if table_name not in PARTITION_CANDIDATES:
            logger.warning("%s is not a partition candidate", table_name)
            return False

        partition_name = f"{table_name}_{year}{month:02d}"
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)

        # Check if partition exists
        exists = await session.execute(
            text(
                "SELECT 1 FROM pg_tables WHERE tablename = :name"
            ),
            {"name": partition_name},
        )
        if exists.scalar():
            return False

        await session.execute(
            text(
                f"CREATE TABLE {partition_name} "
                f"PARTITION OF {table_name} "
                f"FOR VALUES FROM ('{start.isoformat()}') "
                f"TO ('{end.isoformat()}')"
            )
        )
        # Create tenant_id index on the partition
        await session.execute(
            text(
                f"CREATE INDEX ix_{partition_name}_tenant "
                f"ON {partition_name} (tenant_id)"
            )
        )
        logger.info("created partition %s", partition_name)
        return True

    @staticmethod
    async def ensure_upcoming_partitions(
        session: AsyncSession,
        table_name: str,
        *,
        months_ahead: int = 2,
    ) -> int:
        """Ensure partitions exist for the next N months."""
        if table_name not in PARTITION_CANDIDATES:
            return 0

        now = datetime.now(UTC)
        created = 0
        for i in range(months_ahead + 1):
            # Calculate target month
            total_months = now.month + i
            target_year = now.year + (total_months - 1) // 12
            target_month = ((total_months - 1) % 12) + 1

            if await PartitionManager.ensure_partition(
                session, table_name,
                year=target_year, month=target_month,
            ):
                created += 1

        return created

    @staticmethod
    async def detach_old_partitions(
        session: AsyncSession,
        table_name: str,
        *,
        older_than_months: int = 12,
    ) -> int:
        """Detach partitions older than N months for archiving (§57).

        Detached partitions can be moved to cheaper storage or exported
        for archival.
        """
        if table_name not in PARTITION_CANDIDATES:
            return 0

        cutoff = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        # Go back N months
        for _ in range(older_than_months):
            if cutoff.month == 1:
                cutoff = cutoff.replace(year=cutoff.year - 1, month=12)
            else:
                cutoff = cutoff.replace(month=cutoff.month - 1)

        # Find and detach old partitions
        result = await session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE tablename LIKE :pattern "
                "ORDER BY tablename",
            ),
            {"pattern": f"{table_name}_%"},
        )
        detached = 0
        for row in result:
            name = row[0]
            # Parse year+month from partition name
            suffix = name.replace(f"{table_name}_", "")
            if len(suffix) == 6:
                p_year = int(suffix[:4])
                p_month = int(suffix[4:])
                partition_date = datetime(p_year, p_month, 1)
                if partition_date < cutoff:
                    # Detach — CONCURRENTLY for zero downtime
                    await session.execute(
                        text(f"ALTER TABLE {name} DETACH PARTITION CONCURRENTLY")
                    )
                    detached += 1
                    logger.info("detached old partition %s", name)

        return detached
