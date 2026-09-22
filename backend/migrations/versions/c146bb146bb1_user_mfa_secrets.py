"""§146: user_mfa_secrets — durable TOTP secrets for the MFA login flow

Revision ID: c146bb146bb1
Revises: c136aa136aa1
Create Date: 2026-09-27

The MFA secret belongs to the USER, not to one of their tenant memberships,
and the login-time MFA check runs BEFORE any tenant GUC is bound — so this
table mirrors the `users` table's treatment exactly: a global table with no
tenant_id column and no RLS. (A tenant_id column would also be picked up by
the generic tenant_isolation DO-block in b2c3d4e5f6a7 and force-RLS'd, which
would hide every row at login and break sign-in.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c146bb146bb1"
down_revision: str | None = "c136aa136aa1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_mfa_secrets",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=False),
        # base64 of the base32 TOTP secret — envelope encryption lands with the §68/69 work.
        sa.Column("totp_secret_encrypted", sa.String(length=255), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "backup_codes_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_mfa_secrets_user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_mfa_secrets")
