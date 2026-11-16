"""import_sessions and import_rows: the durable state of a merchant's data import.

Revision ID: fe2026111221
Revises: fe2026111220
Create Date: 2026-11-16 18:40:00.000000

The old CSV import ran every row inside one request and kept nothing: no file, no mapping, no
per-row verdict. A 100k-variant file cannot be done that way, and a merchant who fixes three bad
rows must not re-upload everything. A session keeps the file pointer, the column mapping and the
options; ``import_rows`` keeps every source row with its status and errors, so validation,
preview, the error report and a retry after a crash all read the database.

``UNIQUE (session_id, sheet, row_number)`` is the idempotency key: loading the same batch twice
cannot create a second copy of a row, and the runner skips rows already ``applied``.

Both tables are tenant-scoped under FORCE row level security, like every other tenant table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111221"
down_revision: str | None = "fe2026111220"
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
        "import_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(15), nullable=False),
        sa.Column("status", sa.String(15), server_default="uploaded", nullable=False),
        sa.Column("file_key", sa.Text()),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer()),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("mapping", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("options", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("stats", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('products','stock','images','customers')", name="ck_import_sessions_kind"
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','analyzed','mapped','validating','validated','running',"
            "'completed','failed','cancelled')",
            name="ck_import_sessions_status",
        ),
    )
    op.create_index("ix_import_sessions_tenant_id", "import_sessions", ["tenant_id"])
    op.create_index(
        "ix_import_sessions_tenant_created", "import_sessions", ["tenant_id", "created_at"]
    )
    _secure("import_sessions")

    op.create_table(
        "import_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("import_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sheet", sa.String(63), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("errors", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("applied_ref", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("session_id", "sheet", "row_number", name="uq_import_rows_position"),
        sa.CheckConstraint(
            "status IN ('pending','valid','error','applied','skipped')",
            name="ck_import_rows_status",
        ),
    )
    op.create_index("ix_import_rows_tenant_id", "import_rows", ["tenant_id"])
    op.create_index("ix_import_rows_session_status", "import_rows", ["session_id", "status"])
    _secure("import_rows")


def downgrade() -> None:
    op.drop_table("import_rows")
    op.drop_table("import_sessions")
