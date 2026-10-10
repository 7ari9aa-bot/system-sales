"""P1-12 provenance for analysis_evidence: which provider and model answered.

Revision ID: fe2026100815
Revises: fe2026100814
Create Date: 2026-10-10 05:10:00.000000

The stored analysis recorded `model` — which is the ALIAS the agent asked for
("fast") — and `prompt_version`. An alias is not a model: it can be re-pointed
at a different provider next week, and then a published answer cannot be
attributed to the thing that produced it. Two nullable columns close that:
the provider that served the call and the concrete model behind the alias.

NULL on rows written before this migration, which is the honest answer rather
than a backfilled guess — nobody recorded it, so nobody can say now.

No RLS work: `analysis_evidence` already carries ENABLE + FORCE +
tenant_isolation (e8f9a0b1c2d3), and new columns ride that policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026100815"
down_revision: str | None = "fe2026100814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_evidence", sa.Column("provider", sa.String(63), nullable=True))
    op.add_column("analysis_evidence", sa.Column("model_version", sa.String(127), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_evidence", "model_version")
    op.drop_column("analysis_evidence", "provider")
