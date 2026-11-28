"""Who may change which setting, at which scope.

``SettingDef.permission`` used to be documentation only: the router checked
``settings:write`` once and then let the caller set any key. This module is the
single decision point and it is called by the service, so no caller can skip it.

Rules, in order:

1. The permission on the definition (default ``settings:write``) lets the holder
   write the key at every scope the key allows.
2. ``settings:branch_write`` lets the holder write a key only when the key is
   ``branch_delegable`` AND the scope is below tenant (branch, warehouse,
   pos_profile, register, channel). Never at tenant level.
3. ``user`` scope is personal: a user may always write their own, and only their own.
4. Anything else is denied with ``PermissionDenied``.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection

from app.modules.errors import PermissionDeniedError
from app.platform.settings.registry import Scope, SettingDef

BRANCH_WRITE = "settings:branch_write"


def authorize_write(
    defn: SettingDef,
    scope: Scope,
    scope_id: uuid.UUID | None,
    *,
    permissions: Collection[str],
    user_id: uuid.UUID | None,
) -> None:
    """Raise ``PermissionDeniedError`` unless the caller may write ``defn`` at ``scope``."""
    if scope is Scope.USER:
        if user_id is not None and scope_id == user_id:
            return
        # Only an owner-grade writer may set another person's preference.
        if defn.permission in permissions:
            return
        raise PermissionDeniedError(f"{defn.key}: a user setting can only be changed by its user")

    if defn.permission in permissions:
        return

    if scope is not Scope.TENANT and defn.branch_delegable and BRANCH_WRITE in permissions:
        return

    needed = defn.permission
    if scope is not Scope.TENANT and defn.branch_delegable:
        needed = f"{defn.permission} or {BRANCH_WRITE}"
    raise PermissionDeniedError(f"{defn.key}: requires {needed} at scope {scope.value!r}")
