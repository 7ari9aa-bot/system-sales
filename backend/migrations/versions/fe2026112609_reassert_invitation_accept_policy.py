"""Re-assert the invitation-accept policy, idempotently.

``fe2026112607`` created ``invitations_accept_read`` and was recorded as
applied, yet on 27 Nov the policy was absent from production while
``alembic_version`` still read ``fe2026112608``: every ``POST
/invitations/accept`` answered 404 "invitation not found" again, and invited
teammates could not join a shop. Re-creating the policy by hand restored the
endpoint immediately (201, membership created), so the object was the whole
difference — the migration's version stamp outlived its effect.

A stamped revision cannot re-run, so this one re-creates the same policy with
``DROP POLICY IF EXISTS`` + ``CREATE``. It is a no-op wherever the policy is
already present, and it converges an environment where it is not, whichever
order that environment was built in. ``app/core/boot.py`` now also fails a
startup invariant when the policy is missing, so the next drift is reported by
the process instead of by a user who cannot accept their invitation.

Revision ID: fe2026112609
Revises: fe2026112608
Create Date: 2026-11-27 01:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112609"
down_revision: str | None = "fe2026112608"
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
