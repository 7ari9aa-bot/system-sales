"""Every active plan includes what the product already ships.

The commercial tables existed with nothing in them, so `entitled()` answered
"nothing is included" for every account and the install route recorded nothing -
the gate had a hole and the button that closes it did nothing. This seeds the
inclusion rows so the chain is real: a plan includes an application, the
subscription decides which plan, and the installation then has a right behind it.

The table was created with a uniqueness rule on (plan_id, application_key), which
assumes plans are global. They are, but the rows are not: RLS scopes every read to
one tenant, so an inclusion written for one account is invisible to the next and
each account needs its own copy. The rule moves to (tenant_id, plan_id,
application_key) first - otherwise the second tenant's insert collides with the
first's and silently does nothing.

Scope is deliberate and conservative: it mirrors what every plan could already
use before the gate existed, so nobody loses a screen they had this morning. Which
application belongs to which tier is a product decision, not a migration's, so
narrowing a plan means deleting rows here on purpose, not guessing them now.
"""

from __future__ import annotations

from alembic import op

revision = "fe2026112708"
down_revision = "fe2026112707"
branch_labels = None
depends_on = None

# The seven registered applications, spelled out rather than imported: a migration
# must keep meaning what it meant when it ran, even if the registry changes later.
APPLICATIONS = (
    "retail.core",
    "retail.purchasing",
    "retail.warehouse",
    "retail.inventory_advanced",
    "customer.engagement",
    "ai.customer_support",
    "ai.business_intelligence",
)

_KEYS_SQL = ", ".join(f"('{key}')" for key in APPLICATIONS)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE plan_application_inclusions "
        "DROP CONSTRAINT IF EXISTS uq_plan_app_inclusion"
    )
    op.execute(
        """
        ALTER TABLE plan_application_inclusions
        ADD CONSTRAINT uq_plan_app_inclusion
        UNIQUE (tenant_id, plan_id, application_key)
        """
    )
    op.execute(
        f"""
        INSERT INTO plan_application_inclusions
            (id, tenant_id, plan_id, application_key, created_at, updated_at)
        SELECT gen_random_uuid(), t.id, p.id, k.application_key, now(), now()
        FROM tenants t
        CROSS JOIN plans p
        CROSS JOIN (VALUES {_KEYS_SQL}) AS k(application_key)
        WHERE p.is_active
        ON CONFLICT (tenant_id, plan_id, application_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM plan_application_inclusions WHERE application_key IN "
        f"({', '.join(repr(key) for key in APPLICATIONS)})"
    )
