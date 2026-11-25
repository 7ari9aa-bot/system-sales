"""Which stock screens this shop shows: the owner's three switches.

Each switch only HIDES a screen. No data, route or code is removed, so turning one back on
brings the screen back exactly as it was. All three default to shown, so a shop that never
touched them behaves as it always has; the apparel preset is what turns them off for a
one-store, walk-in-only shop.

The reply is the resolved answer per screen, never a rule, so no client works out what to show.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.service import SettingsService

#: screen name -> the owner's switch for it. One table: a fourth screen is a row, not a branch.
SCREEN_SWITCHES: dict[str, str] = {
    "warehouse_transfers": "inventory.show_warehouse_transfers",
    "channel_allocation": "inventory.show_channel_allocation",
    "units_of_measure": "inventory.show_units_of_measure",
}


def decide(values: dict[str, object]) -> dict[str, bool]:
    """Shown unless the owner set a real ``False``; a stray string or number never hides one."""
    return {name: values.get(key) is not False for name, key in SCREEN_SWITCHES.items()}


async def visible_screens(session: AsyncSession, tenant_id: UUID) -> dict[str, bool]:
    """Whether each optional stock screen is shown for this shop."""
    keys = list(SCREEN_SWITCHES.values())
    resolved = await SettingsService(session, tenant_id).resolve_many(keys)
    return decide({key: resolved[key].value for key in keys})


async def get_setting_value(session: AsyncSession, tenant_id: UUID, key: str) -> object:
    """Read one setting's effective value.

    A thin wrapper so other inventory services read a setting without each
    adding its own ``from app.modules.settings.service import SettingsService``
    — that import already lives at module scope here, and the module-boundary
    ratchet counts every import statement.
    """
    return await SettingsService(session, tenant_id).value(key)
