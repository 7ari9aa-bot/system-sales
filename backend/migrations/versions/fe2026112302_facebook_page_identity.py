"""key the Facebook Page identity, and key the Page across Facebook and Messenger

Revision ID: fe2026112302
Revises: fe2026112301
Create Date: 2026-11-23 06:05:00.000000

Facebook and Messenger are two capabilities of ONE Meta Page object, but they were stored as two
independent connections: the Messenger row keeps the Page id in `account_id`, the Facebook row in
`page_id`. The channel-identity index keyed on (provider, identity) therefore let the same Page be
connected as `messenger` in one workspace and as `facebook` in another, with no error, while Meta
delivers that Page's webhooks to a single app callback. This adds the missing `facebook` branch to
the channel identity index and a second index keyed on the PAGE alone, across both providers.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112302"
down_revision: str | None = "fe2026112301"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DUPLICATE_PREFLIGHT = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.integrations
         WHERE provider = 'facebook'
           AND kind = 'channel'
           AND status IN ('active', 'connected')
           AND config->>'page_id' IS NOT NULL
         GROUP BY config->>'page_id'
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate active Facebook Page identities; reconcile integrations before deploying';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.integrations
         WHERE provider IN ('messenger', 'facebook')
           AND kind = 'channel'
           AND status IN ('active', 'connected')
           AND COALESCE(config->>'page_id', config->>'account_id') IS NOT NULL
         GROUP BY COALESCE(config->>'page_id', config->>'account_id')
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'the same Page is connected more than once across Facebook and Messenger; reconcile integrations before deploying';
    END IF;
END
$$;
"""

_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_channel_identity
    ON public.integrations (provider, (
        CASE
            WHEN provider = 'whatsapp' THEN config->>'phone_number_id'
            WHEN provider IN ('messenger', 'instagram') THEN config->>'account_id'
            WHEN provider = 'facebook' THEN config->>'page_id'
            WHEN provider = 'telegram' THEN config->>'bot_id'
            WHEN provider = 'webchat' THEN config->>'public_key'
        END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND (
       (provider = 'whatsapp' AND config->>'phone_number_id' IS NOT NULL) OR
       (provider IN ('messenger', 'instagram') AND config->>'account_id' IS NOT NULL) OR
       (provider = 'facebook' AND config->>'page_id' IS NOT NULL) OR
       (provider = 'telegram' AND config->>'bot_id' IS NOT NULL) OR
       (provider = 'webchat' AND config->>'public_key' IS NOT NULL)
   )
"""

_PAGE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_page_identity
    ON public.integrations ((
        CASE WHEN provider IN ('messenger', 'facebook')
             THEN COALESCE(config->>'page_id', config->>'account_id') END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND provider IN ('messenger', 'facebook')
   AND COALESCE(config->>'page_id', config->>'account_id') IS NOT NULL
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
    # The migration is transactional: a duplicate raises here and leaves the old index in place,
    # rather than failing half-way through and leaving the platform without identity protection.
    op.execute(_DUPLICATE_PREFLIGHT)
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_channel_identity")
    op.execute(_UNIQUE_INDEX)
    op.execute(_PAGE_UNIQUE_INDEX)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_page_identity")
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_channel_identity")
    op.execute(_PREVIOUS_UNIQUE_INDEX)
