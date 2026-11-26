"""Let a public invitation-accept request read its own invitation row.

``invitations`` is FORCE ROW LEVEL SECURITY with only ``tenant_isolation``, so
``POST /invitations/accept`` — which by definition runs before the caller has a
tenant — selected zero rows and answered 404 "invitation not found" for every
token. Invited teammates could never join a shop.

The fix is the possession pattern already used for ``password_reset_tokens``:
presenting the 32-char secret grants read of that single row. The endpoint
binds ``app.invitation_token`` before the lookup, then binds the invitation's
own tenant so the accept can update the row it just proved possession of.

Revision ID: fe2026112607
Revises: fe2026112606
Create Date: 2026-11-26 11:35:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112607"
down_revision: str | None = "fe2026112606"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invitations_accept_read ON invitations")
    op.execute(
        """
        CREATE POLICY invitations_accept_read ON invitations
        FOR SELECT
        USING (token = NULLIF(current_setting('app.invitation_token', true), ''))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invitations_accept_read ON invitations")
