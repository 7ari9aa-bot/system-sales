"""owner_memories and owner_memory_settings: what the shop owner told the assistant.

Revision ID: fe2026111205
Revises: fe2026111204
Create Date: 2026-11-13 00:30:00.000000

A SEPARATE table from ``memories``. ``memories`` is the customer agent's: it is keyed by customer,
read by knowledge retrieval and listed behind settings:write. Putting the owner's private notes
there would let the customer-facing agent reach them. These tables belong to one USER (staff in
the same shop share a tenant but not a memory), sit under FORCE row level security, and are
written only through ``OwnerMemoryService``, which refuses secrets and instructions.

``forget`` deletes the row. A "deleted" flag would leave the owner's words in the table after they
asked for them to be gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111205"
down_revision: str | None = "fe2026111204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        f"""DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def upgrade() -> None:
    op.create_table(
        "owner_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source", sa.String(15), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # lower-cased, whitespace-collapsed copy of content: the "same memory twice" key
        sa.Column("content_key", sa.Text(), nullable=False),
        # clock_timestamp(), not now(): now() is frozen at the start of the transaction, so notes
        # saved in one request would all carry the same instant and "newest" would be a coin flip.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('explicit','inferred')", name="ck_owner_memories_source"),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 500", name="ck_owner_memories_length"
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "content_key", name="uq_owner_memories_user_content"
        ),
    )
    op.create_index("ix_owner_memories_tenant_user", "owner_memories", ["tenant_id", "user_id"])
    _secure("owner_memories")

    op.create_table(
        "owner_memory_settings",
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name="pk_owner_memory_settings"),
    )
    _secure("owner_memory_settings")


def downgrade() -> None:
    op.drop_table("owner_memory_settings")
    op.drop_table("owner_memories")
