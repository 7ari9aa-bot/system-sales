"""backfill the language-only customer tool rows on EXISTING tenants.

Revision ID: fe2026101713
Revises: fe2026101712
Create Date: 2026-10-18 00:00:00.000000

The scope-cut migration deleted the removed tools' rows but added nothing —
provisioning only INSERTS at tenant creation, so every pre-existing customer
agent was left with two tools (find_product_by_image, search_knowledge) and
no catalog, store-info or escalation surface at all. The runtime authorizes
against the registry AND the per-tenant rows: a missing row means the agent
answers from nothing.

This inserts the missing language-only tool rows for every customer-kind
agent, idempotently (ON CONFLICT DO NOTHING — provisioning owns creation and
never overwrites merchant tool edits, this only fills gaps, same semantics).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026101713"
down_revision: str | None = "fe2026101712"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TOOLS = (
    "search_catalog",
    "get_product_details",
    "get_product_photos",
    "get_store_info",
    "handover_to_human",
)


def upgrade() -> None:
    for tool in _NEW_TOOLS:
        op.execute(
            f"""
            INSERT INTO agent_tools (id, tenant_id, agent_id, name, policy, is_active)
            SELECT gen_random_uuid(), a.tenant_id, a.id, '{tool}', '{{}}'::jsonb, true
            FROM agents a
            WHERE a.kind = 'customer'
            ON CONFLICT (tenant_id, agent_id, name) DO NOTHING
            """
        )


def downgrade() -> None:
    # The rows are pure backfill; removing them restores the pre-migration
    # gap rather than any earlier state, so the downgrade is a no-op.
    pass
