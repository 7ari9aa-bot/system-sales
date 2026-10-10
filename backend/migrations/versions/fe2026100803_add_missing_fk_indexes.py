"""Add missing indexes on foreign-key columns.

Addresses 180 unindexed foreign keys flagged by Supabase Performance Advisor
lint 0001_unindexed_foreign_keys.  Each index is created only when its table
AND every indexed column exist, and with IF NOT EXISTS, so the migration is
re-entrant and runs on a fresh database as well as on the live one.

The column guard is not decoration: the first production deploy of this
migration aborted on `ix_pos_cash_movements_created_by` because production's
`pos_cash_movements` predates the `created_by` column — the table exists while
the column it should index does not.  Guarding only the table cannot express
"index the columns the table actually has"; skipping a drifted column is the
honest reading of "add the index where the FK is".

Revision ID: fe2026100803
Revises: fe2026100802
Create Date: 2026-10-08 20:15:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "fe2026100803"
down_revision: str | None = "fe2026100802"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# All foreign-key columns that lack a covering index, grouped by domain.
# Format: (index_name, table_name, column_expression)
# For composite FKs we list multiple columns separated by commas.
# ---------------------------------------------------------------------------
_INDEXES: list[tuple[str, str, str]] = [
    # ── Marketing / Ads ──────────────────────────────────────────────────
    ("ix_ad_sets_campaign_id", "ad_sets", "campaign_id"),
    ("ix_ads_ad_set_id", "ads", "ad_set_id"),

    # ── Customers / Identity ─────────────────────────────────────────────
    ("ix_addresses_customer_id", "addresses", "customer_id"),
    ("ix_consents_customer_id", "consents", "customer_id"),
    ("ix_customer_events_customer_id", "customer_events", "customer_id"),
    ("ix_customer_identities_customer_id", "customer_identities", "customer_id"),
    ("ix_customer_tags_tag_id", "customer_tags", "tag_id"),
    ("ix_customers_merged_into", "customers", "merged_into_customer_id"),
    ("ix_data_subject_requests_customer_id", "data_subject_requests", "customer_id"),
    ("ix_data_subject_requests_requested_by", "data_subject_requests", "requested_by_user_id"),
    ("ix_identity_merge_candidates_a", "identity_merge_candidates", "customer_a_id"),
    ("ix_identity_merge_candidates_b", "identity_merge_candidates", "customer_b_id"),
    ("ix_identity_merge_candidates_decided_by", "identity_merge_candidates", "decided_by_user_id"),
    ("ix_identity_merge_events_canonical", "identity_merge_events", "canonical_customer_id"),
    ("ix_identity_merge_events_merged_away", "identity_merge_events", "merged_away_customer_id"),
    ("ix_identity_merge_events_performed_by", "identity_merge_events", "performed_by_user_id"),

    # ── AI / Agent domain ────────────────────────────────────────────────
    ("ix_agent_profile_versions_created_by", "agent_profile_versions", "created_by"),
    ("ix_agent_profile_versions_published_by", "agent_profile_versions", "published_by"),
    ("ix_agent_profile_versions_profile", "agent_profile_versions", "tenant_id, profile_id"),
    ("ix_agent_profiles_agent", "agent_profiles", "tenant_id, agent_id"),
    ("ix_agent_runs_agent_id", "agent_runs", "agent_id"),
    ("ix_agent_runs_conversation_id", "agent_runs", "conversation_id"),
    ("ix_agent_tools_agent_id", "agent_tools", "agent_id"),
    ("ix_ai_budget_policies_agent_id", "ai_budget_policies", "agent_id"),
    ("ix_ai_evaluations_agent_id", "ai_evaluations", "agent_id"),
    ("ix_ai_handovers_claimed_by", "ai_handovers", "claimed_by_user_id"),
    ("ix_ai_handovers_conversation_id", "ai_handovers", "conversation_id"),
    ("ix_ai_handovers_run_id", "ai_handovers", "run_id"),
    ("ix_ai_sessions_conversation_id", "ai_sessions", "conversation_id"),
    ("ix_ai_usage_agent_id", "ai_usage", "agent_id"),
    ("ix_model_calls_run_id", "model_calls", "run_id"),
    ("ix_prompts_agent_id", "prompts", "agent_id"),
    ("ix_tool_calls_agent_tool_id", "tool_calls", "agent_tool_id"),
    ("ix_tool_calls_run_id", "tool_calls", "run_id"),
    ("ix_eval_cases_agent", "eval_cases", "tenant_id, agent_id"),

    # ── AI usage partitions ──────────────────────────────────────────────
    ("ix_ai_usage_2026_09_agent_id", "ai_usage_2026_09", "agent_id"),
    ("ix_ai_usage_2026_10_agent_id", "ai_usage_2026_10", "agent_id"),
    ("ix_ai_usage_2026_11_agent_id", "ai_usage_2026_11", "agent_id"),
    ("ix_ai_usage_2026_12_agent_id", "ai_usage_2026_12", "agent_id"),
    ("ix_ai_usage_2027_01_agent_id", "ai_usage_2027_01", "agent_id"),
    ("ix_ai_usage_default_agent_id", "ai_usage_default", "agent_id"),
    ("ix_ai_usage_pre_partition_agent_id", "ai_usage_pre_partition", "agent_id"),

    # ── Analysis / Evidence ──────────────────────────────────────────────
    ("ix_analysis_evidence_location_id", "analysis_evidence", "location_id"),
    ("ix_analysis_evidence_run_id", "analysis_evidence", "run_id"),
    ("ix_analysis_evidence_workspace_id", "analysis_evidence", "workspace_id"),
    ("ix_analysis_findings_evidence_id", "analysis_findings", "evidence_id"),
    ("ix_analysis_findings_location_id", "analysis_findings", "location_id"),
    ("ix_analysis_findings_workspace_id", "analysis_findings", "workspace_id"),

    # ── Approvals ────────────────────────────────────────────────────────
    ("ix_approval_requests_approved_by", "approval_requests", "approved_by_user_id"),
    ("ix_approval_requests_conversation_id", "approval_requests", "conversation_id"),
    ("ix_approval_requests_run_id", "approval_requests", "run_id"),

    # ── Assignments / Conversations ──────────────────────────────────────
    ("ix_assignments_assigned_by", "assignments", "assigned_by_user_id"),
    ("ix_assignments_assigned_to", "assignments", "assigned_to_user_id"),
    ("ix_assignments_conversation_id", "assignments", "conversation_id"),
    ("ix_conversations_assignee", "conversations", "assignee_user_id"),
    ("ix_conversations_customer_id", "conversations", "customer_id"),
    ("ix_conv_agent_states_tenant_id", "conversation_agent_states", "tenant_id"),

    # ── Attachments / Messages ───────────────────────────────────────────
    ("ix_attachments_conversation_id", "attachments", "conversation_id"),
    ("ix_attachments_message_id", "attachments", "message_id"),
    ("ix_messages_conversation_id", "messages", "conversation_id"),
    ("ix_messages_reply_to", "messages", "reply_to_message_id"),
    ("ix_messages_sender_user_id", "messages", "sender_user_id"),

    # ── Attribution / Conversions / Touchpoints ──────────────────────────
    ("ix_attributions_conversion_id", "attributions", "conversion_id"),
    ("ix_attributions_touchpoint_id", "attributions", "touchpoint_id"),
    ("ix_conversions_customer_id", "conversions", "customer_id"),
    ("ix_conversions_order_id", "conversions", "order_id"),
    ("ix_conversions_touchpoint_id", "conversions", "touchpoint_id"),
    ("ix_touchpoints_ad_id", "touchpoints", "ad_id"),
    ("ix_touchpoints_ad_set_id", "touchpoints", "ad_set_id"),
    ("ix_touchpoints_campaign_id", "touchpoints", "campaign_id"),
    ("ix_touchpoints_customer_id", "touchpoints", "customer_id"),

    # ── Audit ────────────────────────────────────────────────────────────
    ("ix_audit_logs_actor_user_id", "audit_logs", "actor_user_id"),

    # ── Authority / Budget ───────────────────────────────────────────────
    ("ix_authority_leases_grant_id", "authority_leases", "grant_id"),
    ("ix_budget_reservations_budget_id", "budget_reservations", "budget_id"),

    # ── Calls / Voice ────────────────────────────────────────────────────
    ("ix_call_legs_call_id", "call_legs", "call_id"),
    ("ix_call_legs_session_id", "call_legs", "session_id"),
    ("ix_call_recordings_call_id", "call_recordings", "call_id"),
    ("ix_call_sessions_call_id", "call_sessions", "call_id"),
    ("ix_calls_conversation_id", "calls", "conversation_id"),
    ("ix_calls_customer_id", "calls", "customer_id"),
    ("ix_calls_phone_number_id", "calls", "phone_number_id"),
    ("ix_ivr_sessions_call_id", "ivr_sessions", "call_id"),

    # ── Campaigns ────────────────────────────────────────────────────────
    ("ix_campaign_runs_campaign_id", "campaign_runs", "campaign_id"),

    # ── Categories ───────────────────────────────────────────────────────
    ("ix_categories_parent_id", "categories", "parent_id"),

    # ── Decision / Dependencies ──────────────────────────────────────────
    ("ix_decision_deps_tenant_id", "decision_dependencies", "tenant_id"),

    # ── Delivery / Webhooks ──────────────────────────────────────────────
    ("ix_delivery_attempts_message_id", "delivery_attempts", "message_id"),
    ("ix_delivery_attempts_webhook_delivery_id", "delivery_attempts", "webhook_delivery_id"),

    # ── Billing / Subscriptions ──────────────────────────────────────────
    ("ix_entitlements_subscription_id", "entitlements", "subscription_id"),
    ("ix_invoices_subscription_id", "invoices", "subscription_id"),
    ("ix_subscriptions_plan_id", "subscriptions", "plan_id"),

    # ── Financial ────────────────────────────────────────────────────────
    ("ix_financial_entries_account_id", "financial_entries", "account_id"),
    ("ix_financial_entries_transaction_id", "financial_entries", "transaction_id"),

    # ── Inventory ────────────────────────────────────────────────────────
    ("ix_inventory_balances_variant_id", "inventory_balances", "variant_id"),
    ("ix_inventory_balances_warehouse_id", "inventory_balances", "warehouse_id"),
    ("ix_inventory_movements_variant_id", "inventory_movements", "variant_id"),
    ("ix_inventory_movements_warehouse_id", "inventory_movements", "warehouse_id"),
    ("ix_inv_rec_findings_location_id", "inventory_reconciliation_findings", "location_id"),
    ("ix_inv_rec_findings_resolved_by", "inventory_reconciliation_findings", "resolved_by"),
    ("ix_inv_rec_findings_variant_id", "inventory_reconciliation_findings", "variant_id"),
    ("ix_inv_rec_findings_warehouse_id", "inventory_reconciliation_findings", "warehouse_id"),
    ("ix_inv_rec_findings_workspace_id", "inventory_reconciliation_findings", "workspace_id"),
    ("ix_inventory_reservations_order_id", "inventory_reservations", "order_id"),
    ("ix_inventory_reservations_variant_id", "inventory_reservations", "variant_id"),
    ("ix_inventory_reservations_warehouse_id", "inventory_reservations", "warehouse_id"),
    ("ix_inventory_transfers_from_warehouse", "inventory_transfers", "from_warehouse_id"),
    ("ix_inventory_transfers_to_warehouse", "inventory_transfers", "to_warehouse_id"),

    # ── Invitations / Tenant users ───────────────────────────────────────
    ("ix_invitations_invited_by", "invitations", "invited_by_user_id"),
    ("ix_invitations_role_id", "invitations", "role_id"),
    ("ix_tenant_users_role_id", "tenant_users", "role_id"),
    ("ix_tenant_users_user_id", "tenant_users", "user_id"),
    ("ix_refresh_tokens_tenant_id", "refresh_tokens", "tenant_id"),

    # ── Jobs ─────────────────────────────────────────────────────────────
    ("ix_jobs_actor_user_id", "jobs", "actor_user_id"),

    # ── Journeys ─────────────────────────────────────────────────────────
    ("ix_journey_runs_customer_id", "journey_runs", "customer_id"),
    ("ix_journey_runs_journey_id", "journey_runs", "journey_id"),

    # ── Leads ────────────────────────────────────────────────────────────
    ("ix_leads_campaign_id", "leads", "campaign_id"),
    ("ix_leads_customer_id", "leads", "customer_id"),
    ("ix_leads_owner_user_id", "leads", "owner_user_id"),

    # ── Memories ─────────────────────────────────────────────────────────
    ("ix_memories_conversation_id", "memories", "conversation_id"),
    ("ix_memories_customer_id", "memories", "customer_id"),

    # ── Notes ────────────────────────────────────────────────────────────
    ("ix_notes_author_user_id", "notes", "author_user_id"),
    ("ix_notes_customer_id", "notes", "customer_id"),

    # ── Notifications ────────────────────────────────────────────────────
    ("ix_notification_digests_user_id", "notification_digests", "user_id"),
    ("ix_notification_prefs_user_id", "notification_preferences", "user_id"),
    ("ix_notifications_customer_id", "notifications", "customer_id"),
    ("ix_notifications_user_id", "notifications", "user_id"),

    # ── Orders ───────────────────────────────────────────────────────────
    ("ix_order_items_order_id", "order_items", "order_id"),
    ("ix_order_items_variant_id", "order_items", "variant_id"),
    ("ix_order_payments_order_id", "order_payments", "order_id"),
    ("ix_order_status_history_changed_by", "order_status_history", "changed_by_user_id"),
    ("ix_order_status_history_order_id", "order_status_history", "order_id"),
    ("ix_orders_customer_id", "orders", "customer_id"),

    # ── POS ──────────────────────────────────────────────────────────────
    ("ix_pos_cash_movements_created_by_user_id", "pos_cash_movements", "created_by_user_id"),
    ("ix_pos_cash_movements_location_id", "pos_cash_movements", "location_id"),
    ("ix_pos_cash_movements_workspace_id", "pos_cash_movements", "workspace_id"),
    ("ix_pos_cash_movements_session_id", "pos_cash_movements", "session_id"),
    ("ix_pos_receipts_location_id", "pos_receipts", "location_id"),
    ("ix_pos_receipts_workspace_id", "pos_receipts", "workspace_id"),
    ("ix_pos_receipts_order_id", "pos_receipts", "order_id"),
    ("ix_pos_receipts_session_id", "pos_receipts", "session_id"),
    ("ix_pos_registers_location_id", "pos_registers", "location_id"),
    ("ix_pos_registers_workspace_id", "pos_registers", "workspace_id"),
    ("ix_pos_registers_warehouse_id", "pos_registers", "warehouse_id"),
    ("ix_pos_sessions_closed_by", "pos_sessions", "closed_by"),
    ("ix_pos_sessions_location_id", "pos_sessions", "location_id"),
    ("ix_pos_sessions_opened_by", "pos_sessions", "opened_by"),
    ("ix_pos_sessions_workspace_id", "pos_sessions", "workspace_id"),
    ("ix_pos_sessions_register_id", "pos_sessions", "register_id"),

    # ── Products ─────────────────────────────────────────────────────────
    ("ix_product_attributes_tenant_id", "product_attributes", "tenant_id"),
    ("ix_product_embeddings_product_id", "product_embeddings", "product_id"),
    ("ix_product_identifiers_location_id", "product_identifiers", "location_id"),
    ("ix_product_identifiers_workspace_id", "product_identifiers", "workspace_id"),
    ("ix_product_identifiers_variant_id", "product_identifiers", "variant_id"),
    ("ix_product_images_variant_id", "product_images", "variant_id"),
    ("ix_product_images_product_id", "product_images", "product_id"),
    ("ix_product_option_values_location_id", "product_option_values", "location_id"),
    ("ix_product_option_values_workspace_id", "product_option_values", "workspace_id"),
    ("ix_product_option_values_option_id", "product_option_values", "option_id"),
    ("ix_product_options_location_id", "product_options", "location_id"),
    ("ix_product_options_workspace_id", "product_options", "workspace_id"),
    ("ix_product_options_product_id", "product_options", "product_id"),
    ("ix_product_prices_variant_id", "product_prices", "variant_id"),
    ("ix_pvov_location_id", "product_variant_option_values", "location_id"),
    ("ix_pvov_workspace_id", "product_variant_option_values", "workspace_id"),
    ("ix_pvov_option_id", "product_variant_option_values", "option_id"),
    ("ix_pvov_option_value_id", "product_variant_option_values", "option_value_id"),
    ("ix_pvov_variant_id", "product_variant_option_values", "variant_id"),
    ("ix_product_variants_product_id", "product_variants", "product_id"),
    ("ix_products_brand_id", "products", "brand_id"),
    ("ix_products_category_id", "products", "category_id"),

    # ── Refunds ──────────────────────────────────────────────────────────
    ("ix_refunds_created_by", "refunds", "created_by_user_id"),
    ("ix_refunds_payment_id", "refunds", "payment_id"),

    # ── RBAC ─────────────────────────────────────────────────────────────
    ("ix_role_permissions_permission_id", "role_permissions", "permission_id"),

    # ── Saved views ──────────────────────────────────────────────────────
    ("ix_saved_views_owner_user_id", "saved_views", "owner_user_id"),

    # ── Shipments ────────────────────────────────────────────────────────
    ("ix_shipments_order_id", "shipments", "order_id"),

    # ── SLA ──────────────────────────────────────────────────────────────
    ("ix_sla_events_conversation_id", "sla_events", "conversation_id"),
    ("ix_sla_events_policy_id", "sla_events", "policy_id"),

    # ── Tasks ────────────────────────────────────────────────────────────
    ("ix_tasks_assignee_user_id", "tasks", "assignee_user_id"),

    # ── Templates ────────────────────────────────────────────────────────
    ("ix_template_approvals_template_id", "template_approvals", "template_id"),

    # ── User location access ─────────────────────────────────────────────
    ("ix_user_location_access_location_id", "user_location_access", "location_id"),

    # ── Workflows ────────────────────────────────────────────────────────
    ("ix_workflow_executions_workflow_id", "workflow_executions", "workflow_id"),
]


def _guarded_index_ddl(index_name: str, table: str, cols: str) -> str:
    """The guarded CREATE INDEX for one entry as a self-contained DO block.

    Extracted verbatim from upgrade() so the guard itself is testable: the
    four scenarios the production abort taught (missing table, present
    column, drifted column, one drifted column feeding several indexes) run
    against a real database in tests/test_fk_index_guard.py.
    """
    wanted = ", ".join(f"('{c.strip()}')" for c in cols.split(","))
    return f"""
            DO $$
            BEGIN
                IF to_regclass('public.{table}') IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1
                       FROM (VALUES {wanted}) AS want(col)
                       WHERE NOT EXISTS (
                           SELECT 1
                           FROM information_schema.columns c
                           WHERE c.table_schema = 'public'
                             AND c.table_name = '{table}'
                             AND c.column_name = want.col
                       )
                   )
                THEN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS {index_name} ' ||
                            'ON public.{table} ({cols})';
                END IF;
            END $$;
            """


def upgrade() -> None:
    for idx_name, table, cols in _INDEXES:
        # Guarded on the table AND its columns, not just the index. Two failures
        # taught this shape:
        #
        # 1. Missing TABLE. `IF NOT EXISTS` makes the index re-entrant but says
        #    nothing about its TABLE: `agent_profiles`, `agent_profile_versions`
        #    and `eval_cases` exist only in the live database, and the
        #    `ai_usage_*` partitions are created dynamically for the months
        #    around whichever date the migration runs — so `ai_usage_2026_09`
        #    is absent on a fresh build and `relation does not exist` aborted
        #    `alembic upgrade head`.
        #
        # 2. Missing COLUMN. Production's `pos_cash_movements` predates its
        #    `created_by` column, so the table guard passed and CREATE INDEX
        #    failed with `column ... does not exist`, aborting the API deploy.
        #    A schema that drifted from the code gets the indexes its columns
        #    allow; backfilling the drifted column is a separate migration.
        op.execute(_guarded_index_ddl(idx_name, table, cols))


def downgrade() -> None:
    for idx_name, _table, _cols in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS public.{idx_name}")
