"""fd2026100412: the users UPDATE policy admits the verification-link flow.

fd2026100410 admitted the reset write via a live-reset-token predicate but
predated the email-verification wave (fd2026100411): verify_email updates
users.email_verified pre-GUC, so the UPDATE policy denied the row and the
flush died with a StaleDataError. The same immutability argument as the
reset clause applies — possession is proven by a token row whose
requested_at sits inside the 24-hour link TTL; consumed_at cannot be used
because the ORM flushes the token's consumption UPDATE BEFORE the user
write (dependents first), and any consumed_at predicate is a StaleDataError
waiting to happen.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fd2026100412"
down_revision: str | None = "fd2026100411"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"
_LIVE_RESET_TOKEN = (
    "EXISTS (SELECT 1 FROM public.password_reset_tokens prt "
    "WHERE prt.user_id = users.id "
    "AND prt.requested_at > now() - interval '1 hour')"
)
_LIVE_VERIFICATION_TOKEN = (
    "EXISTS (SELECT 1 FROM public.email_verification_tokens evt "
    "WHERE evt.user_id = users.id "
    "AND evt.requested_at > now() - interval '24 hours')"
)


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_self_update ON public.users")
    op.execute(
        f"""CREATE POLICY users_self_update ON public.users
            FOR UPDATE USING (
                id = {_USER_GUARD}
                OR {_LIVE_RESET_TOKEN}
                OR {_LIVE_VERIFICATION_TOKEN}
            )
            WITH CHECK (
                id = {_USER_GUARD}
                OR {_LIVE_RESET_TOKEN}
                OR {_LIVE_VERIFICATION_TOKEN}
            )"""
    )


def downgrade() -> None:
    # Restore the fd2026100410 policy verbatim.
    op.execute("DROP POLICY IF EXISTS users_self_update ON public.users")
    op.execute(
        f"""CREATE POLICY users_self_update ON public.users
            FOR UPDATE USING (id = {_USER_GUARD} OR {_LIVE_RESET_TOKEN})
            WITH CHECK (id = {_USER_GUARD} OR {_LIVE_RESET_TOKEN})"""
    )
