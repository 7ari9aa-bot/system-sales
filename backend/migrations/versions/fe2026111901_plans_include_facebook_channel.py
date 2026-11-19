"""Plans that include Messenger now include the Facebook channel too.

Revision ID: fe2026111901
Revises: fe2026111804
Create Date: 2026-11-19 03:45:00.000000

WHY. The Facebook connect button is the same page-messaging grant as Messenger, and the channels page
offers it, but no plan listed ``facebook``: connecting it failed with "plan does not include this
channel" on every plan except Enterprise. ``provision.py`` only INSERTs a plan that is missing, so
fixing the list there does not reach plans already in the database.

Only plans that already carry ``messenger`` gain ``facebook``. Starter and Basic are untouched: which
channels a cheaper plan gets is a pricing decision, not something to widen here. A plan that already
lists ``facebook`` or uses ``"*"`` is left as it is.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111901"
down_revision: str | None = "fe2026111804"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE plans
        SET features = jsonb_set(
            features,
            '{channels}',
            (features->'channels') || '"facebook"'::jsonb
        )
        WHERE jsonb_typeof(features->'channels') = 'array'
          AND (features->'channels') ? 'messenger'
          AND NOT (features->'channels') ? 'facebook'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE plans
        SET features = jsonb_set(
            features,
            '{channels}',
            (features->'channels') - 'facebook'
        )
        WHERE jsonb_typeof(features->'channels') = 'array'
          AND (features->'channels') ? 'facebook'
          AND (features->'channels') ? 'messenger'
        """
    )
