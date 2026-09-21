"""phase9: external commerce, voice, saga, growth, platform, money

Adds tables for:
- External commerce source-of-truth policies (§161)
- Voice advanced architecture (§36): calls, sessions, legs, recordings, IVR
- Saga / process manager (§139)
- Journey runs (§175 Phase 5)
- Campaign runs (§175 Phase 5)
- Notification preferences + digests (§166)
- Tenant restore jobs (§164)
- DR policy + restore test runs (§70)

Revision ID: f9b0c1d2e3f4
Revises: e7a8b9c0d1e2
Create Date: 2026-09-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f9b0c1d2e3f4"
down_revision: str | None = "e7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- §161: Source of Truth Policies ---
    op.create_table(
        "source_of_truth_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(63), nullable=False),
        sa.Column("entity_type", sa.String(31), nullable=False),
        sa.Column("source_mode", sa.String(15), nullable=False),
        sa.Column("sync_direction", sa.String(15), nullable=False),
        sa.Column("conflict_policy", sa.String(15), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_version", sa.String(255), nullable=True),
        sa.Column("internal_version", sa.String(255), nullable=True),
        sa.Column("config", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider", "entity_type", name="uq_sot_tenant_provider_entity"),
    )
    op.create_index("ix_sot_tenant_provider", "source_of_truth_policies", ["tenant_id", "provider"])

    # --- §36: Voice Architecture ---
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("number", sa.String(31), nullable=False),
        sa.Column("provider", sa.String(63), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(15), server_default="available", nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_phone_numbers_tenant_status", "phone_numbers", ["tenant_id", "status"])

    op.create_table(
        "calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("phone_number_id", sa.UUID(), nullable=True),
        sa.Column("direction", sa.String(15), nullable=False),
        sa.Column("status", sa.String(20), server_default="ringing", nullable=False),
        sa.Column("from_number", sa.String(31), nullable=True),
        sa.Column("to_number", sa.String(31), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("provider_metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["phone_number_id"], ["phone_numbers.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_calls_tenant_status", "calls", ["tenant_id", "status"])
    op.create_index("ix_calls_tenant_customer", "calls", ["tenant_id", "customer_id"])

    op.create_table(
        "call_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("session_type", sa.String(15), nullable=False),
        sa.Column("status", sa.String(15), server_default="active", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_call_sessions_tenant_call", "call_sessions", ["tenant_id", "call_id"])

    op.create_table(
        "call_legs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("direction", sa.String(15), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=True),
        sa.Column("sdp", sa.Text(), nullable=True),
        sa.Column("codec", sa.String(63), nullable=True),
        sa.Column("status", sa.String(15), server_default="ringing", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["call_sessions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_call_legs_tenant_call", "call_legs", ["tenant_id", "call_id"])

    op.create_table(
        "call_recordings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="recording", nullable=False),
        sa.Column("transcript_id", sa.String(255), nullable=True),
        sa.Column("consent_captured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_recordings_tenant_call", "call_recordings", ["tenant_id", "call_id"])

    op.create_table(
        "ivr_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("menu_id", sa.String(255), nullable=True),
        sa.Column("path", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("collected_inputs", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(15), server_default="active", nullable=False),
        sa.Column("outcome", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ivr_sessions_tenant_call", "ivr_sessions", ["tenant_id", "call_id"])

    # --- §139: Sagas ---
    op.create_table(
        "sagas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("saga_type", sa.String(63), nullable=False),
        sa.Column("aggregate_type", sa.String(63), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("current_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("step_results", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("context", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sagas_tenant_status", "sagas", ["tenant_id", "status"])
    op.create_index("ix_sagas_tenant_aggregate", "sagas", ["tenant_id", "aggregate_type", "aggregate_id"])

    # --- §175: Journey Runs ---
    op.create_table(
        "journey_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("current_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_journey_runs_tenant_status", "journey_runs", ["tenant_id", "status"])
    op.create_index("ix_journey_runs_tenant_customer", "journey_runs", ["tenant_id", "customer_id"])

    # --- §175: Campaign Runs ---
    op.create_table(
        "campaign_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(15), server_default="queued", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_recipients", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("cursor", sa.String(64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_campaign_runs_tenant_status", "campaign_runs", ["tenant_id", "status"])

    # --- §166: Notification Preferences + Digests ---
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("push_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("quiet_start", sa.Time(), nullable=True),
        sa.Column("quiet_end", sa.Time(), nullable=True),
        sa.Column("timezone", sa.String(63), server_default="Africa/Cairo", nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("digest_frequency", sa.String(15), server_default="hourly", nullable=False),
        sa.Column("priority_overrides", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notif_prefs_tenant_user", "notification_preferences", ["tenant_id", "user_id"])

    op.create_table(
        "notification_digests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("latest_payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("channels", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notif_digests_tenant_user_status", "notification_digests", ["tenant_id", "user_id", "status"])
    op.create_index("ix_notif_digests_dedupe", "notification_digests", ["dedupe_key", "status"])

    # --- §164: Tenant Restore ---
    op.create_table(
        "tenant_restore_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("target_tenant_id", sa.UUID(), nullable=False),
        sa.Column("backup_point", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_types", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(25), server_default="pending", nullable=False),
        sa.Column("recovery_db_ref", sa.String(255), nullable=True),
        sa.Column("extraction_results", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("validation_results", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("restore_results", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_restore_tenant_status", "tenant_restore_jobs", ["tenant_id", "status"])

    # --- §70: DR Policy + Restore Tests ---
    op.create_table(
        "dr_policy",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("rpo_minutes", sa.Integer(), server_default="5", nullable=False),
        sa.Column("rto_minutes", sa.Integer(), server_default="30", nullable=False),
        sa.Column("backup_retention_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("pitr_window_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("restore_test_cron", sa.String(63), server_default="0 2 * * 0", nullable=False),
        sa.Column("last_restore_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_restore_test_status", sa.String(15), nullable=True),
        sa.Column("runbook_ref", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "restore_test_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(15), server_default="scheduled", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restore_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("data_loss_seconds", sa.Integer(), nullable=True),
        sa.Column("checks", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("errors", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_restore_tests_status", "restore_test_runs", ["status"])

    # --- RLS on all new tenant-scoped tables ---
    for table in [
        "source_of_truth_policies",
        "phone_numbers",
        "calls",
        "call_sessions",
        "call_legs",
        "call_recordings",
        "ivr_sessions",
        "sagas",
        "journey_runs",
        "campaign_runs",
        "notification_preferences",
        "notification_digests",
        "tenant_restore_jobs",
    ]:
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('app.tenant_id')::uuid)"
        )


def downgrade() -> None:
    for table in [
        "restore_test_runs",
        "dr_policy",
        "tenant_restore_jobs",
        "notification_digests",
        "notification_preferences",
        "campaign_runs",
        "journey_runs",
        "sagas",
        "ivr_sessions",
        "call_recordings",
        "call_legs",
        "call_sessions",
        "calls",
        "phone_numbers",
        "source_of_truth_policies",
    ]:
        op.drop_table(table)
