"""Scope columns for the Customer Agent vision tables.

The three vision tables landed in a1b2c3d4e5f6 WITHOUT the columns their
models declare: ProductEmbedding, ProductAttribute and ConversationAgentState
all inherit WorkspaceScopeMixin (app/core/model_kit.py), so the first INSERT
into any of them fails with UndefinedColumnError on workspace_id. Same shape
as the Q4 retrofit (d4a7c1e9f0b5): nullable workspace_id/location_id, FKs
with ondelete SET NULL (a removed hierarchy node never deletes business
rows), and one index per column. NULL keeps every existing row tenant-wide —
no backfill, no behavior change until a scoped request writes.

Calls are written out per table (no loop): the static model/migration drift
guard reads this file's AST and must see every column as a literal
add_column argument.

Revision ID: b4c5d6e7f8a9
Revises: a1b2c3d4e5f6
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_embeddings", sa.Column("workspace_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "product_embeddings", sa.Column("location_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        op.f("ix_product_embeddings_workspace_id"),
        "product_embeddings",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_embeddings_location_id"),
        "product_embeddings",
        ["location_id"],
        unique=False,
    )
    op.create_foreign_key(
        None,
        "product_embeddings",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        None,
        "product_embeddings",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "product_attributes", sa.Column("workspace_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "product_attributes", sa.Column("location_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        op.f("ix_product_attributes_workspace_id"),
        "product_attributes",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_attributes_location_id"),
        "product_attributes",
        ["location_id"],
        unique=False,
    )
    op.create_foreign_key(
        None,
        "product_attributes",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        None,
        "product_attributes",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "conversation_agent_states", sa.Column("workspace_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "conversation_agent_states", sa.Column("location_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        op.f("ix_conversation_agent_states_workspace_id"),
        "conversation_agent_states",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_agent_states_location_id"),
        "conversation_agent_states",
        ["location_id"],
        unique=False,
    )
    op.create_foreign_key(
        None,
        "conversation_agent_states",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        None,
        "conversation_agent_states",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # TimestampMixin declares created_at AND updated_at; a1b2c3d4e5f6 only
    # stamped updated_at on this table, so the model's created_at read fails.
    op.add_column(
        "conversation_agent_states",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Dropping the columns drops their FKs too on Postgres — no need to name
    # constraints the upgrade left auto-named.
    op.drop_index(
        op.f("ix_conversation_agent_states_location_id"),
        table_name="conversation_agent_states",
    )
    op.drop_index(
        op.f("ix_conversation_agent_states_workspace_id"),
        table_name="conversation_agent_states",
    )
    op.drop_column("conversation_agent_states", "location_id")
    op.drop_column("conversation_agent_states", "workspace_id")
    op.drop_column("conversation_agent_states", "created_at")

    op.drop_index(
        op.f("ix_product_attributes_location_id"), table_name="product_attributes"
    )
    op.drop_index(
        op.f("ix_product_attributes_workspace_id"), table_name="product_attributes"
    )
    op.drop_column("product_attributes", "location_id")
    op.drop_column("product_attributes", "workspace_id")

    op.drop_index(
        op.f("ix_product_embeddings_location_id"), table_name="product_embeddings"
    )
    op.drop_index(
        op.f("ix_product_embeddings_workspace_id"), table_name="product_embeddings"
    )
    op.drop_column("product_embeddings", "location_id")
    op.drop_column("product_embeddings", "workspace_id")
