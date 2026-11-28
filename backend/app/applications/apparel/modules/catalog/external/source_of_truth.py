"""Spec §161 — External Commerce Source of Truth Policy.

Every entity synced from an external store (Shopify/WooCommerce/CSV) has
an explicit policy defining: which side is authoritative, the sync
direction, the conflict resolution strategy, and version tracking.

This is NOT a blind two-way sync. The policy makes the rules visible and
auditable — a product price coming from Shopify with a HYBRID policy and
"external_wins" conflict strategy is an intentional decision, not an
accident.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import NotFoundError, ValidationError
from app.core.model_kit import TenantMixin, TimestampMixin

# Entity types that can have an external source-of-truth policy.
_ENTITY_TYPES = frozenset(
    {
        "product",
        "inventory",
        "order",
        "customer",
        "payment",
    }
)

# Source modes:
#   INTERNAL   — our DB is the truth; external is a read-only copy
#   EXTERNAL   — external store is the truth; we mirror
#   HYBRID     — both sides can write; conflict_policy decides
_SOURCE_MODES = frozenset({"internal", "external", "hybrid"})

# Sync directions:
#   inbound    — external → internal (we pull)
#   outbound   — internal → external (we push)
#   bidirectional — both
_SYNC_DIRECTIONS = frozenset({"inbound", "outbound", "bidirectional"})

# Conflict policies (for HYBRID mode):
#   external_wins  — external version takes precedence
#   internal_wins  — internal version takes precedence
#   latest_wins    — compare last_modified timestamps
#   manual         — surface conflict for human resolution
_CONFLICT_POLICIES = frozenset(
    {
        "external_wins",
        "internal_wins",
        "latest_wins",
        "manual",
    }
)


class SourceOfTruthPolicy(TenantMixin, TimestampMixin, Base):
    """§161: per-entity source-of-truth policy for external commerce sync."""

    __tablename__ = "source_of_truth_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The external provider this policy applies to (shopify, woocommerce, csv, ...)
    provider: Mapped[str] = mapped_column(String(63), nullable=False)
    # The entity type this policy governs
    entity_type: Mapped[str] = mapped_column(String(31), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(15), nullable=False)
    sync_direction: Mapped[str] = mapped_column(String(15), nullable=False)
    conflict_policy: Mapped[str] = mapped_column(String(15), nullable=False)
    # Tracking fields for reconciliation — TIMESTAMPTZ in the migration
    # (f9b0c1d2e3f4), so the model must declare timezone=True.
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # External version marker (e.g. Shopify's updated_at or version_id)
    external_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Internal version marker (our row's updated_at or version column)
    internal_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Config: field mappings, ignored fields, etc.
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "entity_type",
            name="uq_sot_tenant_provider_entity",
        ),
        Index("ix_sot_tenant_provider", "tenant_id", "provider"),
    )


class SourceOfTruthService:
    """Manage external commerce source-of-truth policies (§161)."""

    @staticmethod
    async def upsert_policy(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        entity_type: str,
        source_mode: str,
        sync_direction: str,
        conflict_policy: str = "external_wins",
        config: dict | None = None,
    ) -> SourceOfTruthPolicy:
        if entity_type not in _ENTITY_TYPES:
            raise ValidationError(f"entity_type must be one of {sorted(_ENTITY_TYPES)}")
        if source_mode not in _SOURCE_MODES:
            raise ValidationError(f"source_mode must be one of {sorted(_SOURCE_MODES)}")
        if sync_direction not in _SYNC_DIRECTIONS:
            raise ValidationError(f"sync_direction must be one of {sorted(_SYNC_DIRECTIONS)}")
        if conflict_policy not in _CONFLICT_POLICIES:
            raise ValidationError(f"conflict_policy must be one of {sorted(_CONFLICT_POLICIES)}")

        from sqlalchemy import select

        existing = (
            await session.execute(
                select(SourceOfTruthPolicy).where(
                    SourceOfTruthPolicy.tenant_id == tenant_id,
                    SourceOfTruthPolicy.provider == provider,
                    SourceOfTruthPolicy.entity_type == entity_type,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.source_mode = source_mode
            existing.sync_direction = sync_direction
            existing.conflict_policy = conflict_policy
            existing.config = config or {}
            await session.flush()
            return existing

        policy = SourceOfTruthPolicy(
            tenant_id=tenant_id,
            provider=provider,
            entity_type=entity_type,
            source_mode=source_mode,
            sync_direction=sync_direction,
            conflict_policy=conflict_policy,
            config=config or {},
        )
        session.add(policy)
        await session.flush()
        return policy

    @staticmethod
    async def get_policy(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        entity_type: str,
    ) -> SourceOfTruthPolicy | None:
        from sqlalchemy import select

        return (
            await session.execute(
                select(SourceOfTruthPolicy).where(
                    SourceOfTruthPolicy.tenant_id == tenant_id,
                    SourceOfTruthPolicy.provider == provider,
                    SourceOfTruthPolicy.entity_type == entity_type,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def mark_synced(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        entity_type: str,
        external_version: str | None = None,
        internal_version: str | None = None,
    ) -> SourceOfTruthPolicy:
        policy = await SourceOfTruthService.get_policy(
            session, tenant_id, provider=provider, entity_type=entity_type
        )
        if policy is None:
            raise NotFoundError(f"no source-of-truth policy for {provider}/{entity_type}")
        policy.last_synced_at = datetime.now(UTC)
        if external_version is not None:
            policy.external_version = external_version
        if internal_version is not None:
            policy.internal_version = internal_version
        await session.flush()
        return policy

    @staticmethod
    async def resolve_conflict(
        policy: SourceOfTruthPolicy,
        *,
        external_value: dict,
        internal_value: dict,
        external_modified_at: datetime | None = None,
        internal_modified_at: datetime | None = None,
    ) -> str:
        """Return 'external', 'internal', or 'manual' for a conflict."""
        if policy.source_mode == "external":
            return "external"
        if policy.source_mode == "internal":
            return "internal"
        # HYBRID — apply conflict policy
        if policy.conflict_policy == "external_wins":
            return "external"
        if policy.conflict_policy == "internal_wins":
            return "internal"
        if policy.conflict_policy == "latest_wins":
            if external_modified_at and internal_modified_at:
                return "external" if external_modified_at >= internal_modified_at else "internal"
            return "external"  # fallback
        return "manual"  # human resolution required
