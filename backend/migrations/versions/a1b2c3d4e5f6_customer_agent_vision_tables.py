"""Customer Agent vision tables: product_embeddings, product_attributes,
conversation_agent_states.

Spec §12.6/§20: the vision stack's owned storage. product_embeddings keys a
768-dim vector to each approved catalog image (``product_images``), pinned to
the embedding model by a UNIQUE constraint — a provider-model change is a full
re-index, never a mixed vector space (the HNSW cosine index answers the
retrieval path's top-k). product_attributes holds the offline-derived
attributes the Decision Engine's consistency factor reads.
conversation_agent_states is the per-conversation state the system owns:
shown_items/sent_media (referents + no-resend) behind state_version.

RLS follows the f4d5e6a7b8c9 pattern — tenant_isolation policies plus grants
guarded by a sales_app role-exists DO block, so CI (which provisions
sales_app after Alembic) and production (role already present) both stay
valid in either deploy order.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_TABLES = ("product_embeddings", "product_attributes", "conversation_agent_states")


def upgrade() -> None:
    op.create_table(
        "product_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_image_id",
            sa.Uuid(),
            sa.ForeignKey("product_images.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("vector", Vector(768), nullable=False),
        sa.Column("model", sa.String(127), nullable=False),
        sa.Column("model_version", sa.String(63), server_default="1", nullable=False),
        sa.Column("content_kind", sa.String(15), server_default="image", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "product_image_id",
            "model",
            "model_version",
            name="uq_product_embeddings_image_model_version",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="CASCADE"
        ),
    )
    # HNSW: the retrieval path is always cosine top-k; build it here so the
    # first index run does not serialize behind an index build at query time.
    op.execute(
        "CREATE INDEX ix_product_embeddings_vector_hnsw "
        "ON product_embeddings USING hnsw (vector vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_product_embeddings_tenant_product "
        "ON product_embeddings (tenant_id, product_id)"
    )

    op.create_table(
        "product_attributes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("color", sa.String(63)),
        sa.Column("material", sa.String(63)),
        sa.Column("style", sa.String(63)),
        sa.Column("category", sa.String(63)),
        sa.Column("model", sa.String(127), nullable=False),
        sa.Column("model_version", sa.String(63), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "product_id",
            "model",
            "model_version",
            name="uq_product_attributes_product_model_version",
        ),
    )

    op.create_table(
        "conversation_agent_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("shown_items", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("sent_media", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "conversation_id", name="uq_conversation_agent_states_conversation"
        ),
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )

    # CI provisions sales_app after Alembic, while production already has it.
    # Guard the grants so both deploy orders remain valid.
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              product_embeddings, product_attributes, conversation_agent_states
              TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
