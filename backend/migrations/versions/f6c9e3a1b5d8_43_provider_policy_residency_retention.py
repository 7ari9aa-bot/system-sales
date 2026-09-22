"""§43 — ai_provider_policies gain data_residency and retention_terms.

The spec's per-tenant provider policy lists Data residency and Retention
policy next to allowed providers/models and the PII flag; the row only had
the latter. Without columns there was nothing to declare and nothing for the
egress gate to enforce — a tenant bound to EU-only data could not say so.

Enforcement lives in policy.decide(): a declared residency checks against
the region recorded on the resolved model config, and an unknown region FAILS
CLOSED. retention_terms is documentation-on-the-row (spec: provider
data-processing terms must be documented before production), not a claim we
can enforce from our side of the wire.

Revision ID: f6c9e3a1b5d8
Revises: e5b8d2f0a1c3
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6c9e3a1b5d8"
down_revision: str | None = "e5b8d2f0a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_policies",
        sa.Column("data_residency", sa.String(length=31), nullable=True),
    )
    op.add_column(
        "ai_provider_policies",
        sa.Column("retention_terms", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_provider_policies", "retention_terms")
    op.drop_column("ai_provider_policies", "data_residency")
