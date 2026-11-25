"""Read the organization-level settings that the UI and reports need.

These three keys (default_language, brand_color, fiscal_year_start_month) are
set in the settings registry but read here — outside the settings module — so
they count as enforced (``ENFORCED_KEYS``) and a change to the key actually
reaches the system, not just a row in the database.

* ``default_language`` drives the UI language the frontend opens in.
* ``brand_color`` is the hex the frontend uses as its CSS accent.
* ``fiscal_year_start_month`` is the month (1-12) reports treat as the start
  of the financial year.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ORG_KEYS = (
    "organization.default_language",
    "organization.brand_color",
    "organization.fiscal_year_start_month",
)


async def organization_config(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    """The tenant's organization settings, resolved via direct SQL.

    Direct SQL avoids a cyclic import (core → settings → ... → core).
    Returns final values with sensible defaults.
    """
    rows = (
        await session.execute(
            text(
                "SELECT key, value->'v' FROM tenant_settings "
                "WHERE tenant_id = :t AND key = ANY(:keys) AND scope = 'tenant'"
            ),
            {"t": tenant_id, "keys": list(_ORG_KEYS)},
        )
    ).all()
    values: dict[str, Any] = {
        "default_language": "ar",
        "brand_color": "#4F46E5",
        "fiscal_year_start_month": 1,
    }
    for key, value in rows:
        if key == "organization.default_language" and isinstance(value, str):
            values["default_language"] = value
        elif key == "organization.brand_color" and isinstance(value, str):
            values["brand_color"] = value
        elif (
            key == "organization.fiscal_year_start_month"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            values["fiscal_year_start_month"] = max(1, min(12, int(value)))
    return values
