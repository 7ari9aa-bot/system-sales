"""Sales Intelligence: eleven tools become three (`si_metric`, `si_shop`, `si_finance`).

Revision ID: fe2026111220
Revises: fe2026111219
Create Date: 2026-11-16 06:30:00.000000

Every tool the model is offered costs a full model round (5 to 15 seconds and several thousand
tokens) each time it is chosen, and one question could call five of them. A small assistant does
better with few tools and a parameter that says which read to run, so the code now offers three.
A shop's agent still HAS the old rows in ``agent_tools``, and the self-heal that attaches missing
tools never removes extra ones, so without this the model would be offered all of them.

* ``si_metric`` and ``si_finance`` already exist on every agent and are NOT touched: whatever a
  shop set on them (switched off, a policy) stays exactly as it was. Their old companions
  (``si_why``, ``si_activity``, ``si_data_status``, ``si_purchasing_summary``) are deleted, so a
  shop that had switched ``si_finance`` off keeps money off even if purchases were on. Nothing a
  shop turned off is turned on.
* ``si_shop`` is new. It is created from the five tools it replaces (``si_top_products``,
  ``si_stock_status``, ``si_cashier_summary``, ``si_find_order``, ``si_find_customer``): active if
  at least one of them was, carrying the first non-empty ``policy`` found. An agent that had none
  of the five (never provisioned them) is left alone and the self-heal attaches the tool later.

The permission of each read is checked when the read runs, so no role gains access through this.

Idempotent: a second run finds no old rows. The downgrade puts the old rows back from the merged
ones (same active flag and policy) and removes ``si_shop``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111220"
down_revision: str | None = "fe2026111219"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTO_SHOP = (
    "si_top_products",
    "si_stock_status",
    "si_cashier_summary",
    "si_find_order",
    "si_find_customer",
)
# the older companions of the two tools that already exist on every agent
_FOLDED_INTO_EXISTING = {
    "si_metric": ("si_why", "si_activity", "si_data_status"),
    "si_finance": ("si_purchasing_summary",),
}
_OLD = _INTO_SHOP + tuple(n for names in _FOLDED_INTO_EXISTING.values() for n in names)


def _quoted(names: Sequence[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO agent_tools (id, agent_id, name, policy, is_active, tenant_id,
                                 workspace_id, location_id)
        SELECT gen_random_uuid(), o.agent_id, 'si_shop',
               COALESCE((array_agg(o.policy ORDER BY o.name)
                         FILTER (WHERE o.policy IS NOT NULL AND o.policy <> '{{}}'::jsonb))[1],
                        '{{}}'::jsonb),
               bool_or(o.is_active), o.tenant_id,
               (array_agg(o.workspace_id))[1], (array_agg(o.location_id))[1]
          FROM agent_tools o
         WHERE o.name IN ({_quoted(_INTO_SHOP)})
         GROUP BY o.agent_id, o.tenant_id
        ON CONFLICT (tenant_id, agent_id, name) DO NOTHING
        """
    )
    op.execute(f"DELETE FROM agent_tools WHERE name IN ({_quoted(_OLD)})")


def downgrade() -> None:
    def put_back(merged: str, old: Sequence[str]) -> None:
        values = ", ".join(f"('{n}')" for n in old)
        op.execute(
            f"""
            INSERT INTO agent_tools (id, agent_id, name, policy, is_active, tenant_id,
                                     workspace_id, location_id)
            SELECT gen_random_uuid(), m.agent_id, n.name, m.policy, m.is_active, m.tenant_id,
                   m.workspace_id, m.location_id
              FROM agent_tools m CROSS JOIN (VALUES {values}) AS n(name)
             WHERE m.name = '{merged}'
            ON CONFLICT (tenant_id, agent_id, name) DO NOTHING
            """
        )

    put_back("si_shop", _INTO_SHOP)
    for merged, old in _FOLDED_INTO_EXISTING.items():
        put_back(merged, old)
    op.execute("DELETE FROM agent_tools WHERE name = 'si_shop'")
