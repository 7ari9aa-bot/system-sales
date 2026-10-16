"""Shared dependency aliases and RBAC gates for AI sub-routers.

Centralises the ``Annotated[TenantContext, Depends(...)]`` shortcuts so every
sub-router imports them from one place rather than re-declaring its own copy.
"""

from typing import Annotated

from fastapi import Depends

from app.core.errors import PermissionDeniedError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]
SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]
AnalyticsCtx = Annotated[TenantContext, Depends(require_permission("analytics:read"))]
# The handover queue is conversation work, so it is gated by the conversation
# permissions rather than by bare tenant membership (`TenantCtxDep`): reading
# the queue needs `conversations:read`, taking or closing an item needs
# `conversations:write`. Tenant isolation is unchanged — `require_permission`
# resolves the tenant the same way and RLS still binds every row.
HandoverReadCtx = Annotated[TenantContext, Depends(require_permission("conversations:read"))]
HandoverWriteCtx = Annotated[TenantContext, Depends(require_permission("conversations:write"))]


class require_ai_approve:
    """RBAC gate for a decision only a human may make: ``ai:approve``.

    Not plain ``require_permission("ai:approve")`` because the tenant owner
    passes without the code being on their role — the owner is the one who would
    have to seed it onto themselves before they could approve anything.

    A class with a ``code`` attribute, mirroring ``require_permission``, so the
    gate a route declares stays introspectable from the outside; as a bare
    closure it was invisible, and the test that pins this route's gate read it
    as "gated by nothing".
    """

    code = "ai:approve"

    async def __call__(self, ctx: TenantCtxDep) -> TenantContext:
        if self.code not in ctx.permission_codes and ctx.role_code != "owner":
            raise PermissionDeniedError(f"missing permission: {self.code}")
        return ctx


ApproveCtx = Annotated[TenantContext, Depends(require_ai_approve())]
