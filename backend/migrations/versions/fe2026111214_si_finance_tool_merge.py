"""Sales Intelligence: two money tools become one (`si_finance`).

Revision ID: fe2026111214
Revises: fe2026111213
Create Date: 2026-11-15 03:30:00.000000

`si_expenses_summary` and `si_profit_summary` were two more choices for the model on every
question. They are one tool, `si_finance`, with a `report`. The code stops
offering the old two; a shop's agent still HAS them in ``agent_tools``, and the self-heal that
attaches missing tools never removes extra ones, so without this the model would be offered both.

This moves each agent from the old rows to ``si_finance``:

* the new row is created from the old ones, so a shop that switched a tool off keeps it off: the
  new tool is active only if at least one of the two was, and it carries the first non-empty
  ``policy`` found (they were all ``{}`` on every shop when this was written);
* then the two old rows are deleted;
* an agent that has neither (never provisioned them) is left alone.

Idempotent: a second run finds no old rows. The downgrade puts the two back from ``si_finance``
(same active flag and policy) and removes it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111214"
down_revision: str | None = "fe2026111213"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("si_expenses_summary", "si_profit_summary")
_NEW = "si_finance"
_OLD_SQL = ", ".join(f"'{n}'" for n in _OLD)


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO agent_tools (id, agent_id, name, policy, is_active, tenant_id,
                                 workspace_id, location_id)
        SELECT gen_random_uuid(), o.agent_id, '{_NEW}',
               COALESCE((array_agg(o.policy ORDER BY o.name)
                         FILTER (WHERE o.policy IS NOT NULL AND o.policy <> '{{}}'::jsonb))[1],
                        '{{}}'::jsonb),
               bool_or(o.is_active), o.tenant_id,
               (array_agg(o.workspace_id))[1], (array_agg(o.location_id))[1]
          FROM agent_tools o
         WHERE o.name IN ({_OLD_SQL})
         GROUP BY o.agent_id, o.tenant_id
        ON CONFLICT (tenant_id, agent_id, name) DO NOTHING
        """
    )
    op.execute(f"DELETE FROM agent_tools WHERE name IN ({_OLD_SQL})")


def downgrade() -> None:
    values = ", ".join(f"('{n}')" for n in _OLD)
    op.execute(
        f"""
        INSERT INTO agent_tools (id, agent_id, name, policy, is_active, tenant_id,
                                 workspace_id, location_id)
        SELECT gen_random_uuid(), m.agent_id, n.name, m.policy, m.is_active, m.tenant_id,
               m.workspace_id, m.location_id
          FROM agent_tools m CROSS JOIN (VALUES {values}) AS n(name)
         WHERE m.name = '{_NEW}'
        ON CONFLICT (tenant_id, agent_id, name) DO NOTHING
        """
    )
    op.execute(f"DELETE FROM agent_tools WHERE name = '{_NEW}'")
