"""plans: add Basic and Business, and remember which Polar product sells each plan.

Revision ID: fe2026111203
Revises: fe2026111202
Create Date: 2026-11-12 17:00:00.000000

The catalogue had starter (free trial), pro and enterprise. The owner priced two more paid tiers on
Polar (Basic 590, Business 3500 a month), so the plans table gets matching rows. The limits are a
first proposal for the owner to edit, not facts: the numbers sit between starter and pro for Basic
and above pro for Business.

SAFETY. Additive only. Two INSERTs guarded by NOT EXISTS (re-running changes nothing, and a plan
the owner already edited is never overwritten) and one nullable column. No tenant is moved: every
existing subscription keeps pointing at the plan it has today, so no limit changes for anyone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111203"
down_revision: str | None = "fe2026111202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("polar_product_id", sa.String(63), nullable=True))
    op.execute(
        """
        INSERT INTO plans (id, code, name, price, currency, interval, features, is_active)
        SELECT gen_random_uuid(), 'basic', 'Basic', 590, 'EGP', 'month',
               '{"max_users": 5, "ai_agents": 1,
                 "channels": ["whatsapp", "telegram", "webchat"]}'::jsonb,
               true
        WHERE NOT EXISTS (SELECT 1 FROM plans WHERE code = 'basic')
        """
    )
    op.execute(
        """
        INSERT INTO plans (id, code, name, price, currency, interval, features, is_active)
        SELECT gen_random_uuid(), 'business', 'Business', 3500, 'EGP', 'month',
               '{"max_users": 40, "ai_agents": 25,
                 "channels": ["whatsapp", "instagram", "messenger", "telegram",
                              "webchat"]}'::jsonb,
               true
        WHERE NOT EXISTS (SELECT 1 FROM plans WHERE code = 'business')
        """
    )


def downgrade() -> None:
    # Refuse to drop a plan somebody is subscribed to: a silent delete would orphan the row.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM subscriptions s JOIN plans p ON p.id = s.plan_id
                WHERE p.code IN ('basic', 'business')
            ) THEN
                RAISE EXCEPTION 'refusing to drop basic/business: in use';
            END IF;
        END $$
        """
    )
    op.execute("DELETE FROM plans WHERE code IN ('basic', 'business')")
    op.drop_column("plans", "polar_product_id")
