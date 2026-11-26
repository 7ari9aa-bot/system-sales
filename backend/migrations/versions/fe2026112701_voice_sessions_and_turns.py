"""The two tables a voice session needs: `voice_sessions` and `voice_turns`.

The voice runtime keeps a live call in memory, but the control plane must be able to answer what
that session is after the worker that opened it is gone, and a phone that retries the same client
key must find the open session instead of opening a second billable call.

Both tables carry `tenant_id` and get the canonical shape the schema-wide gate enforces: FORCE RLS
plus exactly one `tenant_isolation` policy guarded by `app.tenant_id`. No audio, no transcript copy
and no recording lives here — media goes to object storage and the transcript stays with the
conversation it belongs to.

Revision ID: fe2026112701
Revises: fe2026112617
Create Date: 2026-11-27 01:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112701"
down_revision: str | None = "fe2026112617"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_TABLES = ("voice_sessions", "voice_turns")


def _canonical(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (tenant_id = {_TENANT_GUARD}) "
        f"WITH CHECK (tenant_id = {_TENANT_GUARD})"
    )


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("principal_type", sa.String(32), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("persona", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("authentication_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scopes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_version", sa.String(24), nullable=False, server_default="v1"),
        sa.Column("provider_session_id", sa.String(128), nullable=True),
        sa.Column("provider_name", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("client_key", sa.String(128), nullable=True),
        sa.Column("last_completed_turn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("close_reason", sa.String(120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ux_voice_sessions_client_key",
        "voice_sessions",
        ["tenant_id", "client_key"],
        unique=True,
        postgresql_where=sa.text("client_key IS NOT NULL"),
    )
    op.create_index("ix_voice_sessions_tenant_state", "voice_sessions", ["tenant_id", "state"])
    op.create_index("ix_voice_sessions_trace", "voice_sessions", ["trace_id"])

    op.create_table(
        "voice_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("voice_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(16), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("input_modality", sa.String(16), nullable=True),
        sa.Column("output_modality", sa.String(16), nullable=True),
        sa.Column("transcript_ref", sa.String(200), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("latency_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("completion_reason", sa.String(80), nullable=True),
        sa.Column("interruption_state", sa.String(32), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ux_voice_turns_session_sequence",
        "voice_turns",
        ["session_id", "sequence_number"],
        unique=True,
    )
    op.create_index("ix_voice_turns_tenant", "voice_turns", ["tenant_id"])

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(_canonical(table))
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sales_app")


def downgrade() -> None:
    op.drop_table("voice_turns")
    op.drop_table("voice_sessions")
