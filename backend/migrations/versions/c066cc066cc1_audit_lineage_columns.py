"""§66: audit_logs lineage columns (source, request_id, correlation_id)

Revision ID: c066cc066cc1
Revises: bb22cc33dd44
Create Date: 2026-09-27

Additive only: three nullable VARCHAR columns plus an index on
(tenant_id, request_id). audit_logs keeps its existing RLS posture on
purpose (ENABLE but NO FORCE; policy allows NULL-tenant platform writes and
matching-tenant writes) — adding columns does not touch the policy, and the
write path (AuditService) populates the new columns from request-scoped
contextvars, so no backfill is needed: pre-existing rows stay NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c066cc066cc1"
down_revision: str | None = "bb22cc33dd44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("source", sa.String(length=63), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_audit_tenant_request",
        "audit_logs",
        ["tenant_id", "request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_request", table_name="audit_logs")
    op.drop_column("audit_logs", "correlation_id")
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "source")
