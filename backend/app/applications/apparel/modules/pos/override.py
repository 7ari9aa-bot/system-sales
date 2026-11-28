"""Manager override: a caller who holds ``pos:override`` may work on another cashier's shift.

That is all it does. There is no PIN, no discount ceiling and no money limit in this release: a
shift is held by one cashier, and a manager (anyone with ``pos:override``) may sell on it,
count it or close it on their behalf.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.modules.identity.deps import TenantCtxDep

OVERRIDE_PERMISSION = "pos:override"


@dataclass(frozen=True, slots=True)
class OverrideGrant:
    """Whether the caller may act on a shift another cashier holds."""

    active: bool


async def resolve_override(ctx: TenantCtxDep) -> OverrideGrant:
    return OverrideGrant(active=OVERRIDE_PERMISSION in ctx.permission_codes)


OverrideDep = Annotated[OverrideGrant, Depends(resolve_override)]

__all__ = ["OVERRIDE_PERMISSION", "OverrideDep", "OverrideGrant", "resolve_override"]
