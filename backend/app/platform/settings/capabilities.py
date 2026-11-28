"""Capabilities: what a shop can do, decided by its vertical and finally by its owner.

A *vertical* (apparel, pharmacy, restaurant, general) is only a starting point: it picks the
default answer for each capability. Each capability is also its own owner setting
(``capability.<name>``), so a pharmacy that wants size and colour variants, or a clothes shop that
tracks expiry, turns it on without any code change. Code asks ``capability_enabled`` and never
compares a vertical's name, which is how a fourth vertical is added as data and not as branches.

This module is pure: it holds the table and the decision. The settings registry builds the owner's
switches from ``CAPABILITIES``, so there is one list and not two to keep in step.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

VERTICALS: tuple[str, ...] = ("general", "apparel", "pharmacy", "restaurant")
DEFAULT_VERTICAL = "general"


@dataclass(frozen=True)
class Capability:
    """One thing a shop may or may not do, with the verticals that start with it switched on."""

    name: str
    on_for: tuple[str, ...]
    label_ar: str
    label_en: str
    description_ar: str
    description_en: str
    # Verticals where this capability is MANDATORY: a rule the shop cannot opt out of (a legal duty
    # of that trade), as opposed to a convenience the owner switches on and off. Empty for every
    # capability today, so nothing is forced anywhere yet; the mechanism is here so the first legal
    # rule is a row of data and not a new code path.
    mandatory_in: tuple[str, ...] = ()


CAPABILITIES: dict[str, Capability] = {
    c.name: c
    for c in (
        Capability(
            "variant_matrix",
            ("apparel",),
            "مصفوفة المقاس واللون",
            "Size and colour matrix",
            "يعرّف المنتج بمقاسات وألوان ويبيع كل تركيبة برصيدها.",
            "Define a product by size and colour and sell each combination with its own stock.",
        ),
        Capability(
            "lot_expiry",
            ("pharmacy",),
            "دفعات وتاريخ صلاحية",
            "Batches and expiry dates",
            "يسجّل كل توريد كدفعة بتاريخ انتهاء ويمنع بيع المنتهي.",
            "Record each delivery as a batch with an expiry date; refuse to sell expired stock.",
        ),
        Capability(
            "fefo_picking",
            ("pharmacy",),
            "صرف الأقرب انتهاءً أولاً",
            "Sell the soonest-expiring first",
            "يصرف من الدفعة الأقرب انتهاءً تلقائياً عند البيع.",
            "Take from the soonest-expiring batch automatically at the till.",
        ),
        Capability(
            "prescription_required",
            ("pharmacy",),
            "أصناف تتطلب روشتة",
            "Prescription-only items",
            "يمنع بيع الصنف المعلّم «بروشتة» دون تسجيل رقم الروشتة.",
            "Block a prescription-only item unless a prescription number is recorded.",
        ),
        Capability(
            "modifiers",
            ("restaurant",),
            "إضافات وخيارات الأصناف",
            "Item add-ons and options",
            "يسمح بإضافات وخيارات على الصنف (حجم، إضافة جبن...).",
            "Allow add-ons and options on an item (size, extra cheese, and so on).",
        ),
        Capability(
            "recipe_bom",
            ("restaurant",),
            "وصفات ومكونات",
            "Recipes and ingredients",
            "يخصم مكونات الصنف من المخزون عند بيعه.",
            "Deduct an item's ingredients from stock when it is sold.",
        ),
        Capability(
            "serial_tracking",
            (),
            "أرقام تسلسلية",
            "Serial numbers",
            "يتتبّع كل وحدة برقمها التسلسلي.",
            "Track each unit by its serial number.",
        ),
        Capability(
            "weight_scale",
            (),
            "بيع بالوزن",
            "Sell by weight",
            "يقبل كميات عشرية ويقرأ الوزن من ميزان.",
            "Accept fractional quantities and read weight from a scale.",
        ),
    )
}


def defaults_for(vertical: str | None) -> dict[str, bool]:
    """The starting answer per capability; an unknown vertical is the plain shop."""
    v = vertical if vertical in VERTICALS else DEFAULT_VERTICAL
    return {name: v in cap.on_for for name, cap in CAPABILITIES.items()}


def is_mandatory(name: str, vertical: str | None) -> bool:
    """Is this capability forced on for the vertical, whatever the owner chose?"""
    cap = CAPABILITIES.get(name)
    if cap is None:
        return False
    v = vertical if vertical in VERTICALS else DEFAULT_VERTICAL
    return v in cap.mandatory_in


def capability_enabled(
    name: str,
    *,
    vertical: str | None,
    overrides: Mapping[str, object] | None = None,
) -> bool:
    """Is this capability on for the shop? The owner's switch wins; otherwise the vertical decides.

    Only a real boolean counts as the owner's choice, so a stray string or number can never switch
    a capability on. A name nobody defined is off. A capability that is mandatory for the vertical
    is on and the owner's switch cannot turn it off.
    """
    if name not in CAPABILITIES:
        return False
    if is_mandatory(name, vertical):
        return True
    chosen = (overrides or {}).get(name)
    if isinstance(chosen, bool):
        return chosen
    return defaults_for(vertical)[name]


async def shop_capabilities(
    session: AsyncSession, tenant_id: UUID, *, workspace_id: UUID | None = None
) -> dict[str, object]:
    """The shop's vertical and the final answer for every capability, as its owner has set them.

    The reply is the resolved answer, never a rule: no client works out what a vertical implies.

    One account can run several activities, each its own workspace with its own vertical and
    capabilities. ``workspace_id`` names the activity; left out, it is the workspace the request
    is in. A request in no workspace (and any worker) reads the account's own values, which is
    exactly what every shop got before workspaces had settings, so nothing changes for it.
    """
    from app.core.tenancy import current_scope
    from app.platform.settings.registry import Scope
    from app.platform.settings.scope_graph import UnknownScopeError
    from app.platform.settings.service import SettingsService  # settings reads itself lazily

    if workspace_id is None:
        workspace_id = current_scope()[0]
    keys = ["business.vertical", *(f"capability.{n}" for n in CAPABILITIES)]
    service = SettingsService(session, tenant_id)
    resolved = None
    if workspace_id is not None:
        try:
            resolved = await service.resolve_many(
                keys, scope=Scope.WORKSPACE, scope_id=workspace_id
            )
        except UnknownScopeError:
            # The workspace went away between the request being admitted and this read. A sale
            # must not fail over a setting, so it reads the account's own answer instead.
            resolved = None
    if resolved is None:
        resolved = await service.resolve_many(keys)
    vertical = resolved["business.vertical"].value
    # Only a setting the owner actually set is a choice; an untouched one is the registry's
    # default (False) and must not outrank the vertical.
    chosen = {
        n: resolved[f"capability.{n}"].value
        for n in CAPABILITIES
        if not resolved[f"capability.{n}"].is_default
    }
    return {
        "vertical": vertical,
        "capabilities": {
            n: capability_enabled(n, vertical=vertical, overrides=chosen) for n in CAPABILITIES
        },
        # The ones the owner cannot switch off here, so a screen can lock the switch.
        "mandatory": sorted(n for n in CAPABILITIES if is_mandatory(n, vertical)),
    }
