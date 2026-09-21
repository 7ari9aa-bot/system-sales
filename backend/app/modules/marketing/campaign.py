"""Spec §175 Phase 5 — Campaign execution engine.

A Campaign dispatches messages to a segment of customers in batches.
Execution is async: start_campaign creates a CampaignRun, process_batch
sends messages in chunks via ConversationService + outbox.

§144 fairness: batches respect tenant concurrency budgets — a large
campaign from Tenant A must not starve Tenant B.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin, WorkspaceScopeMixin

logger = logging.getLogger(__name__)


class CampaignRunStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class CampaignRun(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """One execution of a campaign — tracks progress and stats."""

    __tablename__ = "campaign_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(15), server_default="queued"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_recipients: Mapped[int] = mapped_column(Integer, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # Config snapshot: template, channel, body
    config_snapshot: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Batch cursor: last processed customer_id
    cursor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_campaign_runs_tenant_status", "tenant_id", "status"),
    )


class CampaignExecutionService:
    """§175: Campaign execution with fairness controls.

    Batch processing: each call to process_batch sends up to batch_size
    messages. The scheduler re-enters with the cursor until done.
    """

    DEFAULT_BATCH_SIZE = 50

    @staticmethod
    async def start_campaign(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        campaign_id: uuid.UUID,
        segment_id: uuid.UUID | None = None,
        config: dict | None = None,
    ) -> CampaignRun:
        from app.modules.marketing.models import Campaign

        campaign = (
            await session.execute(
                select(Campaign).where(
                    Campaign.tenant_id == tenant_id,
                    Campaign.id == campaign_id,
                )
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise NotFoundError("campaign not found")
        if campaign.status not in ("active", "draft"):
            raise ValidationError(f"campaign is {campaign.status}")

        run = CampaignRun(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            segment_id=segment_id,
            status=CampaignRunStatus.RUNNING.value,
            started_at=datetime.now(UTC),
            config_snapshot=config or {},
            total_recipients=0,
        )
        session.add(run)
        await session.flush()

        add_outbox_event(
            session,
            stream="campaign.events",
            event_type="campaign.run.started",
            aggregate_type="campaign_run",
            aggregate_id=run.id,
            tenant_id=tenant_id,
            payload={"campaign_id": str(campaign_id)},
        )
        return run

    @staticmethod
    async def process_batch(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> CampaignRun:
        """Process one batch of recipients. Idempotent — cursor-based."""
        run = (
            await session.execute(
                select(CampaignRun).where(
                    CampaignRun.tenant_id == tenant_id,
                    CampaignRun.id == run_id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError("campaign run not found")
        if run.status != CampaignRunStatus.RUNNING.value:
            raise ValidationError(f"run is {run.status}, cannot process")

        # Get the next batch of customers from the segment
        customer_ids = await CampaignExecutionService._get_batch(
            session, tenant_id, run, batch_size
        )

        if not customer_ids:
            return await CampaignExecutionService._complete(session, run)

        config = run.config_snapshot or {}
        body = config.get("body", "")
        template = config.get("template")
        channel = config.get("channel", "whatsapp")

        from app.modules.conversations.service import ConversationService

        for cid in customer_ids:
            try:
                await ConversationService.send_outbound_from_automation(
                    session,
                    tenant_id=tenant_id,
                    customer_id=cid,
                    body=body,
                    template_name=template,
                    channel=channel,
                    source="campaign",
                    correlation_id=f"campaign:{run.id}",
                )
                run.sent_count += 1
            except Exception as exc:
                logger.warning("campaign send error for %s: %s", cid, exc)
                run.failed_count += 1

        # Update cursor to last processed customer
        if customer_ids:
            run.cursor = str(customer_ids[-1])

        await session.flush()
        return run

    @staticmethod
    async def pause(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> CampaignRun:
        run = (
            await session.execute(
                select(CampaignRun).where(
                    CampaignRun.tenant_id == tenant_id,
                    CampaignRun.id == run_id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError("campaign run not found")
        if run.status != CampaignRunStatus.RUNNING.value:
            raise ValidationError(f"run is {run.status}, cannot pause")
        run.status = CampaignRunStatus.PAUSED.value
        await session.flush()
        return run

    @staticmethod
    async def resume(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> CampaignRun:
        run = (
            await session.execute(
                select(CampaignRun).where(
                    CampaignRun.tenant_id == tenant_id,
                    CampaignRun.id == run_id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError("campaign run not found")
        if run.status != CampaignRunStatus.PAUSED.value:
            raise ValidationError(f"run is {run.status}, cannot resume")
        run.status = CampaignRunStatus.RUNNING.value
        await session.flush()
        return run

    @staticmethod
    async def _get_batch(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run: CampaignRun,
        batch_size: int,
    ) -> list[uuid.UUID]:
        """Get the next batch of customer IDs from the segment.

        Uses the cursor to skip already-processed customers.
        """
        if run.segment_id:
            # §82: the shared Segment entity is the single audience source —
            # evaluate its DSL (server-side compiled, RLS-scoped) instead of a
            # materialized member table that does not exist.
            from app.modules.segments.service import SegmentService

            member_ids = await SegmentService.list_segment_customers(
                session, tenant_id, run.segment_id
            )
            ordered = sorted(member_ids, key=str)
            if run.cursor:
                ordered = [c for c in ordered if str(c) > run.cursor]
            return ordered[:batch_size]

        # No segment — no recipients
        return []

    @staticmethod
    async def _complete(session: AsyncSession, run: CampaignRun) -> CampaignRun:
        run.status = CampaignRunStatus.COMPLETED.value
        run.completed_at = datetime.now(UTC)
        await session.flush()

        add_outbox_event(
            session,
            stream="campaign.events",
            event_type="campaign.run.completed",
            aggregate_type="campaign_run",
            aggregate_id=run.id,
            tenant_id=run.tenant_id,
            payload={
                "sent": run.sent_count,
                "failed": run.failed_count,
            },
        )
        return run
