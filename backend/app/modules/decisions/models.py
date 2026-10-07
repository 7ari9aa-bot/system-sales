"""DECISIONS domain models — decisions + decision_dependencies (V12).

Enum-like columns are plain Strings per the house convention
(``app/core/model_kit.py``): the closed vocabularies live as frozensets beside
the classes and are enforced by the one state machine in the service — never
``sa.Enum`` (PG ENUM migration churn). The vocabularies below are the V12
ones, verbatim.

Cross-module references (``decisions.evidence_set_id`` pointing at the
evidence module's set, and the mirror ``evidence_sets.decision_id``) are plain
UUID columns with no FK: the two aggregates reference each other by id, and
circular foreign keys would tie the two migrations together without adding a
guarantee the services do not already enforce (same precedent as
``webhook_events.tenant_id``).

``command_hash`` exists but is written by Wave B (core/commands.py); the
column is reserved now so the Wave B migration is additive-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import TenantMixin

#: V12 risk tiers — decides whether the chain needs an approval and the TTL.
RISK_LEVELS: frozenset[str] = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})

#: V12 approval vocabulary (§135 binding state, carried beside the machine).
APPROVAL_STATES: frozenset[str] = frozenset(
    {"NOT_REQUIRED", "PENDING", "APPROVED", "DENIED", "EXPIRED", "REVOKED"}
)

#: V12 decision lifecycle — every value ``decision_status`` may carry.
DECISION_STATUSES: frozenset[str] = frozenset(
    {
        "PROPOSED",
        "VERIFIED",
        "PENDING_APPROVAL",
        "APPROVED",
        "STALE",
        "DENIED",
        "EXPIRED",
        "REVOKED",
        "EXECUTED",
    }
)

#: TTL for HIGH/CRITICAL decisions when the caller does not pin one: an
#: approval on a stale world is worse than no approval (V12's 60s rule).
HIGH_RISK_TTL_SECONDS = 60
_HIGH_RISKS = frozenset({"HIGH", "CRITICAL"})


class Decision(TenantMixin, Base):
    """One proposed mutation of the world, with its evidence and version pins.

    The row is append-only in its CONTENT: action, arguments, hashes and the
    resource_versions map are pinned at propose time and never edited. What
    the state machine moves is the status/approval bookkeeping only.
    """

    __tablename__ = "decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # §66 actor vocabulary: human | ai | automation | system | integration
    actor_type: Mapped[str | None] = mapped_column(String(31))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    intent: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_arguments: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    policy_version: Mapped[int | None] = mapped_column(Integer)
    # allowed: RISK_LEVELS (V12)
    risk_level: Mapped[str] = mapped_column(String(15), nullable=False)
    # allowed: APPROVAL_STATES (V12 §135)
    approval_state: Mapped[str] = mapped_column(
        String(15), nullable=False, server_default="NOT_REQUIRED"
    )
    # Evidence pin — plain UUID into app/modules/evidence (no FK; see docstring).
    evidence_set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    evidence_set_hash: Mapped[str | None] = mapped_column(String(64))
    dependency_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    # Map like {"product:P1": 91, "inventory:P1/W1": 144} — what the world
    # looked like when the decision was minted; Wave B's lease re-checks it.
    resource_versions: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # allowed: DECISION_STATUSES — enforced ONLY by DecisionService._apply_transition
    decision_status: Mapped[str] = mapped_column(
        String(31), nullable=False, server_default="PROPOSED"
    )
    request_id: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # sha256 over (action + normalized_arguments canonical JSON) — computed.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Wave B: canonical command_hash (tenant-pinned). Column reserved now so
    # the Wave B migration is additive-only; nothing writes it in Wave A.
    command_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_decisions_tenant_status", "tenant_id", "decision_status"),
        Index("ix_decisions_tenant_expires", "tenant_id", "expires_at"),
    )


class DecisionDependency(TenantMixin, Base):
    """One resource version the decision was minted against (V12 snapshot).

    Rows are immutable snapshots: when a dependency moves, the decision goes
    STALE — the snapshot is never patched forward.
    """

    __tablename__ = "decision_dependencies"

    dependency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decisions.decision_id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # sha256 of the normalized value — computed by the service when a value is
    # given, so the digest is canonical and reproducible.
    value_digest: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    freshness_sla_seconds: Mapped[int | None] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_decision_dependencies_decision", "decision_id"),)
