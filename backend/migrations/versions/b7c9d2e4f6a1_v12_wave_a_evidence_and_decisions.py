"""V12 Wave A — the Evidence Platform and the Decision Plane

Revision ID: b7c9d2e4f6a1
Revises: d8a1b2c3d4e5
Create Date: 2026-09-27

Four tenant-scoped tables (ADR-060: the V12 machinery lands inside the
existing modules layout):

1. ``evidence_facts``            — one observed claim, hashed at write time
                                   (content_hash = sha256 of the claim).
2. ``evidence_sets``             — an immutable assembly with its
                                   deterministic evidence_set_hash.
3. ``decisions``                 — the Decision Plane row: what was about to
                                   happen, on what evidence, against which
                                   resource versions, in which state.
4. ``decision_dependencies``     — the resource-version snapshot a decision
                                   was minted against.

Column names are the V12 spec's, verbatim — the primary keys are ``fact_id``,
``evidence_set_id``, ``decision_id`` and ``dependency_id`` (not ``id``), and
``decisions.command_hash`` is created now so the Wave B migration is
additive-only (nothing writes it in Wave A).

Enum-like columns are plain Strings with the vocabularies enforced in the
services (house rule — never PG ENUM): evidence source_type / classification
/ trust and the decision risk_level / approval_state / decision_status.

Cross-references between the two modules (``evidence_sets.decision_id``,
``decisions.evidence_set_id``) are plain UUID columns with NO foreign key —
the aggregates reference each other by id and circular FKs would tie the
migrations together without adding a guarantee. The same-module child
(``decision_dependencies.decision_id``) DOES carry a named FK with CASCADE,
as every tenant-scoped child does.

RLS: all four get the canonical treatment — ENABLE + FORCE + a
``tenant_isolation`` policy keyed on the ``app.tenant_id`` GUC through the
NULLIF guard, so an unbound session matches ZERO rows instead of raising
(the d8a1b2c3d4e5 / c9d0e1f2a3b4 idiom).

One statement per ``op.execute()`` — asyncpg's extended-query protocol
rejects multiple commands in a single call.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c9d2e4f6a1"
down_revision: str | None = "d8a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE + the standard tenant_isolation policy for one table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.{table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def upgrade() -> None:
    # decisions FIRST: decision_dependencies carries a real FK to it.
    op.create_table(
        "decisions",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        # allowed (§66 vocabulary): human | ai | automation | system | integration
        sa.Column("actor_type", sa.String(length=31), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "normalized_arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        # allowed: LOW | MEDIUM | HIGH | CRITICAL
        sa.Column("risk_level", sa.String(length=15), nullable=False),
        # allowed: NOT_REQUIRED | PENDING | APPROVED | DENIED | EXPIRED | REVOKED
        sa.Column(
            "approval_state", sa.String(length=15), nullable=False,
            server_default="NOT_REQUIRED",
        ),
        # Evidence pin — plain UUID into the evidence module (no FK by design).
        sa.Column("evidence_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_set_hash", sa.String(length=64), nullable=True),
        sa.Column("dependency_snapshot_hash", sa.String(length=64), nullable=True),
        # Map like {"product:P1": 91, "inventory:P1/W1": 144}.
        sa.Column(
            "resource_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # allowed: PROPOSED | VERIFIED | PENDING_APPROVAL | APPROVED | STALE
        #        | DENIED | EXPIRED | REVOKED | EXECUTED
        sa.Column(
            "decision_status", sa.String(length=31), nullable=False,
            server_default="PROPOSED",
        ),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        # Wave B: canonical command_hash. Column reserved now; no writer yet.
        sa.Column("command_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_decisions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_decisions_tenant_status", "decisions", ["tenant_id", "decision_status"]
    )
    op.create_index(
        "ix_decisions_tenant_expires", "decisions", ["tenant_id", "expires_at"]
    )

    op.create_table(
        "evidence_facts",
        sa.Column("fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        # allowed: SERVICE | DATABASE | EXTERNAL_API | HUMAN | AGENT | MEMORY
        sa.Column("source_type", sa.String(length=31), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_version", sa.BigInteger(), nullable=True),
        sa.Column("resource_version", sa.BigInteger(), nullable=True),
        sa.Column("freshness_sla_seconds", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        # allowed: PUBLIC | INTERNAL | CUSTOMER_DATA | SENSITIVE | PII
        #        | FINANCIAL | CREDENTIAL | SECRET
        sa.Column(
            "classification", sa.String(length=31), nullable=False,
            server_default="INTERNAL",
        ),
        # sha256 hex of the claim content — computed by the service.
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        # allowed: UNVERIFIED | OBSERVED | VALIDATED | SYSTEM_ASSERTED
        sa.Column(
            "trust", sa.String(length=31), nullable=False, server_default="UNVERIFIED"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_evidence_facts_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fact_id"),
    )
    op.create_index(
        "ix_evidence_facts_tenant_subject",
        "evidence_facts",
        ["tenant_id", "subject_type", "subject_id"],
    )
    op.create_index(
        "ix_evidence_facts_tenant_content", "evidence_facts", ["tenant_id", "content_hash"]
    )

    op.create_table(
        "evidence_sets",
        sa.Column("evidence_set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "fact_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("evidence_set_hash", sa.String(length=64), nullable=False),
        # Back-reference to the consuming decision (plain UUID — no FK by design).
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_evidence_sets_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("evidence_set_id"),
    )
    op.create_index(
        "ix_evidence_sets_tenant_created", "evidence_sets", ["tenant_id", "created_at"]
    )

    op.create_table(
        "decision_dependencies",
        sa.Column("dependency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_version", sa.BigInteger(), nullable=False),
        # sha256 of the normalized value (computed by the service).
        sa.Column("value_digest", sa.String(length=64), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_sla_seconds", sa.Integer(), nullable=True),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_decision_dependencies_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.decision_id"],
            name=op.f("fk_decision_dependencies_decision_id_decisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dependency_id"),
    )
    op.create_index(
        "ix_decision_dependencies_decision",
        "decision_dependencies",
        ["decision_id"],
    )

    # Every tenant table gets the canonical isolation treatment — the schema
    # sweep (tests/security/test_schema_wide_rls_policies.py) holds this as
    # the invariant, so a new table arrives WITH it or fails CI.
    _enable_rls("decisions")
    _enable_rls("evidence_facts")
    _enable_rls("evidence_sets")
    _enable_rls("decision_dependencies")


def downgrade() -> None:
    # Reverse of upgrade: children before parents, indexes with their tables.
    op.drop_index(
        "ix_decision_dependencies_decision", table_name="decision_dependencies"
    )
    op.drop_table("decision_dependencies")
    op.drop_index("ix_evidence_sets_tenant_created", table_name="evidence_sets")
    op.drop_table("evidence_sets")
    op.drop_index(
        "ix_evidence_facts_tenant_content", table_name="evidence_facts"
    )
    op.drop_index(
        "ix_evidence_facts_tenant_subject", table_name="evidence_facts"
    )
    op.drop_table("evidence_facts")
    op.drop_index("ix_decisions_tenant_expires", table_name="decisions")
    op.drop_index("ix_decisions_tenant_status", table_name="decisions")
    op.drop_table("decisions")
