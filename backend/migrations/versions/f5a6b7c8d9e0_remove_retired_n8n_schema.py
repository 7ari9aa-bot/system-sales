"""remove the retired n8n integration schema

Revision ID: f5a6b7c8d9e0
Revises: f4d5e6a7b8c9
Create Date: 2026-09-29

The automation runtime and WhatsApp delivery now run inside FastAPI workers.
The old tenant-scoped service-token table was used only by the retired n8n
adapter. ``workflows`` no longer supports an external execution backend.

The production preflight for this migration verified that all affected tables
are empty and that no foreign keys reference ``tenant_service_tokens``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "f4d5e6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("workflows", "n8n_workflow_ref")
    op.drop_column("workflows", "execution_backend")
    op.drop_table("tenant_service_tokens")


def downgrade() -> None:
    op.create_table(
        "tenant_service_tokens",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=127), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rotated_from_id"], ["tenant_service_tokens.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_service_tokens_tenant_id", "tenant_service_tokens", ["tenant_id"])
    op.create_index(
        "uq_tenant_service_tokens_hash",
        "tenant_service_tokens",
        ["token_hash"],
        unique=True,
    )
    op.add_column(
        "workflows",
        sa.Column(
            "execution_backend",
            sa.String(length=15),
            nullable=False,
            server_default="internal",
        ),
    )
    op.add_column("workflows", sa.Column("n8n_workflow_ref", sa.String(length=255), nullable=True))
