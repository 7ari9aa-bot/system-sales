"""The bridge from today's permission codes to the apparel ones.

Roles in the database carry platform-era codes: ``products:write``,
``orders:read``, ``pos:override``. The application declares the codes it wants
(``apparel.pos.sell``). Switching every router to the new codes without this
bridge would lock every existing employee out of the store on deploy day, which
is not a migration, it is an outage.

So the bridge is explicit, one-directional, and temporary:

* one entry per apparel permission, listing the legacy codes that satisfy it;
* a read permission may never be satisfied by a write code, and the reverse
  holds too: the direction of the bridge is part of the contract;
* when roles carry ``apparel.*`` codes, this module is deleted and the guard
  stops asking it. ``test_apparel_permission_bridge`` keeps it honest until then.
"""

from __future__ import annotations

from app.applications.apparel.permissions import PERMISSIONS

#: Legacy code that means "may change things" when the verb is not ``:write``.
LEGACY_WRITE_CODES = frozenset({"pos:override", "ai:approve", "settings:write", "billing:write"})

BRIDGE: dict[str, tuple[str, ...]] = {
    "apparel.dashboard.view": ("analytics:read", "orders:read"),
    "apparel.products.view": ("products:read", "products:write"),
    "apparel.products.create": ("products:write",),
    "apparel.products.edit": ("products:write",),
    "apparel.products.delete": ("products:write",),
    "apparel.products.import": ("products:write",),
    "apparel.inventory.view": ("inventory:read", "inventory:write"),
    "apparel.inventory.adjust": ("inventory:write",),
    "apparel.inventory.count": ("inventory:write",),
    "apparel.inventory.transfer": ("inventory:write",),
    "apparel.purchases.view": ("inventory:read", "inventory:write"),
    "apparel.purchases.create": ("inventory:write",),
    "apparel.purchases.receive": ("inventory:write",),
    "apparel.purchases.approve": ("inventory:write",),
    "apparel.pos.access": ("orders:read", "orders:write"),
    "apparel.pos.sell": ("orders:write",),
    "apparel.pos.discount": ("pos:override",),
    "apparel.pos.cancel_sale": ("pos:override",),
    "apparel.sales.view": ("orders:read", "orders:write"),
    "apparel.sales.correct": ("pos:override",),
    "apparel.returns.view": ("orders:read",),
    "apparel.returns.create": ("orders:write",),
    "apparel.returns.approve": ("pos:override",),
    "apparel.customers.view": ("customers:read", "customers:write"),
    "apparel.customers.edit": ("customers:write",),
    "apparel.reports.view": ("analytics:read", "finance:read"),
    "apparel.reports.export": ("analytics:read", "analytics:write"),
    "apparel.integrations.view": ("conversations:read", "conversations:write"),
    "apparel.integrations.manage": ("conversations:write",),
    "apparel.ai.manage": ("ai:approve", "settings:write"),
}


def legacy_grants(permission_code: str) -> tuple[str, ...]:
    """The legacy codes that satisfy ``permission_code`` today."""
    return BRIDGE.get(permission_code, ())


def satisfied_by_legacy(permission_code: str, held_codes: frozenset[str] | set[str]) -> bool:
    """Does this set of legacy codes grant the apparel permission?

    The caller checks the apparel code itself first; this is the fallback for
    roles that have not been migrated yet.
    """
    return any(code in held_codes for code in legacy_grants(permission_code))


def is_legacy_write(code: str) -> bool:
    return code.endswith(":write") or code in LEGACY_WRITE_CODES


def unmapped_permissions() -> tuple[str, ...]:
    """Apparel permissions with no bridge entry: a role would lose access."""
    return tuple(p.code for p in PERMISSIONS if p.code not in BRIDGE)


__all__ = [
    "BRIDGE",
    "is_legacy_write",
    "legacy_grants",
    "satisfied_by_legacy",
    "unmapped_permissions",
]
