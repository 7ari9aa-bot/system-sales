"""§47/M10 remainder — a tenant declares which day it lives in.

Analytics has bucketed on the MERCHANT's calendar day since gap M10, but the
zone it buckets in came from ONE deployment-wide ``ANALYTICS_TIMEZONE`` (UTC
fallback), because ``tenants`` had no timezone column: ``analytics/timekit.py``
said so out loud. A shop in Cairo and a shop in Dubai therefore shared a "day",
and every sale near local midnight landed on the wrong one for at least one of
them.

This is the same shape §47 solved for money. Money was a Python literal in eight
files until ``tenants.currency`` made the tenant the single answer to "what is
money here", validated at the write boundary and audited. ``tenants.timezone``
does that for the calendar: the zone becomes a property of the merchant, not of
the deployment, and the resolution order in ``timekit.resolve_timezone`` is
caller zone -> this column -> ``ANALYTICS_TIMEZONE`` -> UTC.

NULL is a meaningful value, not a gap: it says "the tenant never chose", and the
deployment zone answers — which is exactly the behaviour every existing row has
today. So there is NO backfill and NO server_default here. Guessing a zone for a
live tenant would silently relabel every day bucket it has ever read, and a
migration cannot know whether a shop keeping books in Cairo counts days there or
in the timezone its server happens to run in.

The CHECK bounds the SHAPE only (a non-empty, path-shaped name that fits the
column). It deliberately does NOT verify that the name is a real IANA zone: that
answer lives in the tzdata database, which Python reads through ``zoneinfo``
(``timekit.resolve_timezone`` / ``ZoneInfo``) and PostgreSQL does not have, so
enforcing it here would mean inventing and maintaining a table of zone names
that drifts the moment tzdata is updated. Resolvability is therefore asserted at
the write boundary — ``TenantSettingsService.set_timezone`` refuses a name
``zoneinfo`` cannot resolve with the same 4xx posture §47 uses for an unknown
currency code — and re-checked by every reader, which fails closed rather than
falling back if a stored name ever stops resolving.

Revision ID: e3b7d2a9c4f1
Revises: d5a1c7e94b02
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b7d2a9c4f1"
down_revision: str | None = "d5a1c7e94b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Shape only — see the docstring for why resolvability is a `zoneinfo`
#: question and not a database one.
_TZ_SHAPE = (
    '"timezone" IS NULL '
    "OR ("
    '  "timezone" <> \'\' '
    '  AND length("timezone") <= 64 '
    '  AND "timezone" ~ \'^[A-Za-z][A-Za-z0-9_/+-]*(/[A-Za-z0-9_+-]+)*$\''
    ")"
)


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint("tenants_timezone_shape", "tenants", _TZ_SHAPE)


def downgrade() -> None:
    op.drop_constraint("tenants_timezone_shape", "tenants", type_="check")
    op.drop_column("tenants", "timezone")
