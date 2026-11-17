"""make a Facebook Page id globally unique across tenants, like Messenger

Facebook Pages shipped on the claim "no migration is needed". That held for
routing (``resolve_channel_tenant`` already maps ``facebook`` to the page id)
but not for uniqueness: the unique index lists providers by name and
``facebook`` was not in it. Two tenants could therefore connect the same Page,
and the routing function (which returns NULL when two active rows match) then
dropped the Page's messages for BOTH of them without any error.

Revision ID: fe2026111722
Revises: fe2026111221
Create Date: 2026-11-17 03:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111722"
down_revision: str | None = "fe2026111221"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Facebook stores the Page id in config.account_id (see the connection spec),
# the same key Messenger and Instagram use, so the identity expression only
# needs the provider added to the existing branch.
_DUPLICATE_PREFLIGHT = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.integrations
         WHERE provider = 'facebook'
           AND kind = 'channel'
           AND status IN ('active', 'connected')
           AND config->>'account_id' IS NOT NULL
         GROUP BY config->>'account_id'
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate active Facebook Page identities; reconcile integrations before deploying';
    END IF;
END
$$;
"""

_DROP_INDEX = "DROP INDEX IF EXISTS public.uq_integrations_active_channel_identity"

_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_channel_identity
    ON public.integrations (provider, (
        CASE
            WHEN provider = 'whatsapp' THEN config->>'phone_number_id'
            WHEN provider IN ('messenger', 'instagram', 'facebook') THEN config->>'account_id'
            WHEN provider = 'telegram' THEN config->>'bot_id'
            WHEN provider = 'webchat' THEN config->>'public_key'
        END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND (
       (provider = 'whatsapp' AND config->>'phone_number_id' IS NOT NULL) OR
       (provider IN ('messenger', 'instagram', 'facebook') AND config->>'account_id' IS NOT NULL) OR
       (provider = 'telegram' AND config->>'bot_id' IS NOT NULL) OR
       (provider = 'webchat' AND config->>'public_key' IS NOT NULL)
   )
"""

_PREVIOUS_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_channel_identity
    ON public.integrations (provider, (
        CASE
            WHEN provider = 'whatsapp' THEN config->>'phone_number_id'
            WHEN provider IN ('messenger', 'instagram') THEN config->>'account_id'
            WHEN provider = 'telegram' THEN config->>'bot_id'
            WHEN provider = 'webchat' THEN config->>'public_key'
        END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND (
       (provider = 'whatsapp' AND config->>'phone_number_id' IS NOT NULL) OR
       (provider IN ('messenger', 'instagram') AND config->>'account_id' IS NOT NULL) OR
       (provider = 'telegram' AND config->>'bot_id' IS NOT NULL) OR
       (provider = 'webchat' AND config->>'public_key' IS NOT NULL)
   )
"""


def upgrade() -> None:
    # The migration is transactional: a duplicate aborts BEFORE the old index
    # is dropped, so a conflict leaves the existing protection in place.
    op.execute(_DUPLICATE_PREFLIGHT)
    op.execute(_DROP_INDEX)
    op.execute(_UNIQUE_INDEX)


def downgrade() -> None:
    op.execute(_DROP_INDEX)
    op.execute(_PREVIOUS_UNIQUE_INDEX)
