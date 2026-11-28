"""EVIDENCE domain models — evidence_facts + evidence_sets (V12 §9).

Both tables are append-only: a superseded fact is a NEW row and an evidence
set is never rewritten, because its ``evidence_set_hash`` is the thing every
downstream Decision pins — an edit path here would be an edit path through
every decision ever minted. There is deliberately no ``updated_at``.

Enum-like columns are plain Strings per the house convention
(``app/core/model_kit.py``): the closed vocabularies live as frozensets beside
the classes and are enforced in the service — never ``sa.Enum`` (PG ENUM
migration churn). The vocabularies below are the V12 §9 ones, verbatim.

Cross-module references (``evidence_sets.decision_id`` and the mirror
``decisions.evidence_set_id``) are plain UUID columns with no FK, like
``webhook_events.tenant_id``: the two aggregates reference each other by id
and a pair of circular foreign keys would only tie the two migrations
together without adding a guarantee the services do not already enforce.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import TenantMixin

#: V12 §9 — how the claim was observed. The untrusted-source rule keys on this
#: (SERVICE/DATABASE are trusted provenance; HUMAN/AGENT claims need corroboration).
SOURCE_TYPES: frozenset[str] = frozenset(
    {"SERVICE", "DATABASE", "EXTERNAL_API", "HUMAN", "AGENT", "MEMORY"}
)

#: V12 §9 — data classification of the claim's content (mirrors the §49 egress
#: vocabulary; drives what a downstream agent may quote).
CLASSIFICATIONS: frozenset[str] = frozenset(
    {"PUBLIC", "INTERNAL", "CUSTOMER_DATA", "SENSITIVE", "PII", "FINANCIAL", "CREDENTIAL", "SECRET"}
)

#: V12 §9 — trust ladder. UNVERIFIED is the default for externally sourced
#: claims; SYSTEM_ASSERTED is reserved for facts this system observed itself.
TRUST_LEVELS: frozenset[str] = frozenset({"UNVERIFIED", "OBSERVED", "VALIDATED", "SYSTEM_ASSERTED"})


class EvidenceFact(TenantMixin, Base):
    """One observed claim about one subject. Immutable; superseded = new row."""

    __tablename__ = "evidence_facts"

    fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_type: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    # allowed: SOURCE_TYPES (V12 §9) — enforced in EvidenceService.create_fact
    source_type: Mapped[str | None] = mapped_column(String(31))
    source_id: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_version: Mapped[int | None] = mapped_column(BigInteger)
    resource_version: Mapped[int | None] = mapped_column(BigInteger)
    freshness_sla_seconds: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    # Free-form provenance from the producer (tool run id, query text, ...).
    # Assembly-time staleness flags are NOT written here — facts are immutable;
    # they are derived and reported per assembly (see EvidenceService).
    provenance: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # allowed: CLASSIFICATIONS (V12 §9)
    classification: Mapped[str] = mapped_column(
        String(31), nullable=False, server_default="INTERNAL"
    )
    # sha256 hex of the claim content — computed by the service, never client-supplied.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # allowed: TRUST_LEVELS (V12 §9)
    trust: Mapped[str] = mapped_column(String(31), nullable=False, server_default="UNVERIFIED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_evidence_facts_tenant_subject", "tenant_id", "subject_type", "subject_id"),
        Index("ix_evidence_facts_tenant_content", "tenant_id", "content_hash"),
    )


class EvidenceSet(TenantMixin, Base):
    """An immutable assembly of fact ids with its deterministic hash (V12 §9).

    ``fact_ids`` is stored SORTED and unique so the row is reproducible from
    its members; ``fact_count`` counts the stored ids. ``evidence_set_hash``
    is sha256 over the sorted (fact_id + content_hash + resource_version)
    triples of the EFFECTIVE facts — same-source repeats of one claim collapse
    to a single effective fact, because a repeated claim from one untrusted
    source is not independent confirmation.
    """

    __tablename__ = "evidence_sets"

    evidence_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fact_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Back-reference to the decision that consumed this set (plain UUID — see
    # the module docstring for why there is no FK).
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_evidence_sets_tenant_created", "tenant_id", "created_at"),)
