"""A shop's own size sets and colours.

The till used to offer fixed lists. The owner now keeps their own: which sets of sizes the shop
sells (men's, babies', shoes) and which colours, in the order they chose. A shop that saved
nothing is shown the built-in lists unchanged, so nothing moves for it, and saving a list replaces
the previous one whole so an owner can drop a colour they no longer sell.

Names are cleaned exactly as the size x colour matrix cleans them, so a size typed here is the same
text the matrix will later build a SKU from.
"""

from __future__ import annotations

import copy
import re
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.apparel.matrix import _clean, normalise_size
from app.modules.catalog.models import ShopColour, ShopSizeSet
from app.modules.errors import ValidationError

#: The sets and colours the till has always offered. Returned as copies, never the originals.
DEFAULT_SIZE_SETS: dict[str, list[str]] = {
    "clothing": ["S", "M", "L", "XL", "XXL"],
    "kids": ["2 سنة", "4 سنوات", "6 سنوات", "8 سنوات"],
    "shoes": ["39", "40", "41", "42", "43"],
    "one": ["مقاس واحد"],
}
DEFAULT_COLOURS: list[dict[str, str | None]] = [
    {"name": "أسود", "hex": "#18181B"},
    {"name": "أبيض", "hex": "#F4F4F5"},
    {"name": "كحلي", "hex": "#1E3A8A"},
    {"name": "أزرق فاتح", "hex": "#60A5FA"},
    {"name": "رمادي", "hex": "#6B7280"},
    {"name": "بيج", "hex": "#D6C3A5"},
    {"name": "أحمر", "hex": "#B91C1C"},
    {"name": "أخضر زيتي", "hex": "#4D7C0F"},
    {"name": "وردي", "hex": "#F472B6"},
    {"name": "بني", "hex": "#78350F"},
]

MAX_SIZE_SETS = 40
MAX_SIZES_PER_SET = 60
MAX_COLOURS = 200
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _fold(text: str) -> str:
    return text.casefold()


def _clean_sizes(raw: object, set_name: str) -> list[str]:
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValidationError(f"size set {set_name!r} needs at least one size")
    if len(raw) > MAX_SIZES_PER_SET:
        raise ValidationError(f"a size set has at most {MAX_SIZES_PER_SET} sizes")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        size = normalise_size(item)
        key = _fold(size)
        if key not in seen:
            seen.add(key)
            out.append(size)
    return out


def _clean_colour(raw: object) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        raise ValidationError("a colour needs a name")
    name = _clean(raw.get("name", ""), "colour name")
    hex_value = raw.get("hex")
    if hex_value in (None, ""):
        return {"name": name, "hex": None}
    if not isinstance(hex_value, str) or not _HEX.match(hex_value):
        raise ValidationError(f"colour hex must look like #RRGGBB, not {hex_value!r}")
    return {"name": name, "hex": hex_value.upper()}


class ShopOptionsService:
    """Read, replace and reset the shop's size sets and colours."""

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        sets = (
            (
                await session.execute(
                    select(ShopSizeSet)
                    .where(ShopSizeSet.tenant_id == tenant_id)
                    .order_by(ShopSizeSet.position, ShopSizeSet.name)
                )
            )
            .scalars()
            .all()
        )
        colours = (
            (
                await session.execute(
                    select(ShopColour)
                    .where(ShopColour.tenant_id == tenant_id)
                    .order_by(ShopColour.position, ShopColour.name)
                )
            )
            .scalars()
            .all()
        )
        return {
            "customised": bool(sets or colours),
            "size_sets": (
                {s.name: list(s.sizes) for s in sets} if sets else copy.deepcopy(DEFAULT_SIZE_SETS)
            ),
            "colours": (
                [{"name": c.name, "hex": c.hex} for c in colours]
                if colours
                else copy.deepcopy(DEFAULT_COLOURS)
            ),
        }

    @staticmethod
    async def save_size_sets(
        session: AsyncSession, tenant_id: UUID, size_sets: dict[str, object]
    ) -> None:
        """Replace the shop's size sets. All of it is checked before anything is touched."""
        if not isinstance(size_sets, dict) or not size_sets:
            raise ValidationError("at least one size set is required")
        if len(size_sets) > MAX_SIZE_SETS:
            raise ValidationError(f"a shop has at most {MAX_SIZE_SETS} size sets")
        cleaned: list[tuple[str, list[str]]] = []
        seen: set[str] = set()
        for raw_name, raw_sizes in size_sets.items():
            name = _clean(raw_name, "size set name")
            if _fold(name) in seen:
                raise ValidationError(f"size set {name!r} is listed twice")
            seen.add(_fold(name))
            cleaned.append((name, _clean_sizes(raw_sizes, name)))
        async with session.begin_nested():
            await session.execute(delete(ShopSizeSet).where(ShopSizeSet.tenant_id == tenant_id))
            for position, (name, sizes) in enumerate(cleaned):
                session.add(
                    ShopSizeSet(tenant_id=tenant_id, name=name, sizes=sizes, position=position)
                )
            await session.flush()

    @staticmethod
    async def save_colours(session: AsyncSession, tenant_id: UUID, colours: list[object]) -> None:
        """Replace the shop's colours. All of it is checked before anything is touched."""
        if not isinstance(colours, list) or not colours:
            raise ValidationError("at least one colour is required")
        if len(colours) > MAX_COLOURS:
            raise ValidationError(f"a shop has at most {MAX_COLOURS} colours")
        cleaned: list[dict[str, str | None]] = []
        seen: set[str] = set()
        for raw in colours:
            colour = _clean_colour(raw)
            key = _fold(str(colour["name"]))
            if key not in seen:
                seen.add(key)
                cleaned.append(colour)
        async with session.begin_nested():
            await session.execute(delete(ShopColour).where(ShopColour.tenant_id == tenant_id))
            for position, colour in enumerate(cleaned):
                session.add(
                    ShopColour(
                        tenant_id=tenant_id,
                        name=str(colour["name"]),
                        hex=colour["hex"],
                        position=position,
                    )
                )
            await session.flush()

    @staticmethod
    async def reset(session: AsyncSession, tenant_id: UUID) -> None:
        """Forget the shop's own lists, so it is shown the built-in ones again."""
        async with session.begin_nested():
            await session.execute(delete(ShopSizeSet).where(ShopSizeSet.tenant_id == tenant_id))
            await session.execute(delete(ShopColour).where(ShopColour.tenant_id == tenant_id))
