"""Disable commerce tools on customer agents — review P0-2.

The customer agent is REPLY-ONLY as of the registry change (definition.py
dropped create_order / add_task / add_tag from CUSTOMER_TOOLS and the
capabilities). Three consequences land here for the EXISTING stores, whose
agent_tools rows still carry the commerce tools enabled:

1. The rows are quarantined (is_active = false) — the same action
   _sync_agent_tools takes for unauthorized tools, applied deterministically
   to every store instead of waiting for the next provisioning pass. The
   runtime refuses unauthorized tools independently, so this row flip is
   belt-and-braces with the registry gate.
2. The rows are NOT deleted: run audit stays intact (the historical
   tool_calls reference them).
3. Downgrade restores is_active = true — the pre-change state.

`_sync_agent_tools` (with the 12.5 fix) will never re-enable them: an
existing disabled row is a decision.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026100817"
down_revision: str | None = "fe2026100816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMERCE_TOOLS = ("create_order", "add_task", "add_tag")


def upgrade() -> None:
    op.execute(
        """
        UPDATE agent_tools at SET is_active = false
        FROM agents a
        WHERE a.id = at.agent_id
          AND a.kind = 'customer'
          AND at.name = ANY(ARRAY['create_order', 'add_task', 'add_tag'])
          AND at.is_active
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE agent_tools at SET is_active = true
        FROM agents a
        WHERE a.id = at.agent_id
          AND a.kind = 'customer'
          AND at.name = ANY(ARRAY['create_order', 'add_task', 'add_tag'])
        """
    )
