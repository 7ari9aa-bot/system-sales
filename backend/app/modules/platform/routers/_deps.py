"""Shared dependencies, pagination bounds, and security gates for platform routers.

Notice: We deliberately omit `from __future__ import annotations` here and in
sub-routers to ensure FastAPI/Pydantic runtime inspection of `Annotated[..., Query(...)]`
and `Header()` parameters works cleanly without stringified annotations.
"""

from typing import Annotated

from fastapi import Query

from app.core.errors import PermissionDeniedError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform import schemas

# The paging knobs every paged platform list shares. One ceiling declared once,
# so a fourth list route cannot be born with a wider one (P7: an unclamped
# `limit` is `LIMIT -1`, which PostgreSQL answers with EVERY row, and a negative
# `offset` is a database error raised as a 500). `tests/test_platform_http_surface.py`
# pins that each paged route refuses both.
PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]


# §160: Platform Admin is a SEPARATE plane from Tenant RBAC.
# The claim is global (users.is_platform_admin, minted into the JWT at login)
# and checked independently of the tenant context — a tenant admin has full
# RBAC inside their tenant but CANNOT touch this plane.
def _require_platform_admin(ctx: TenantContext) -> None:
    """Gate: only the global is_platform_admin JWT claim opens the admin plane.

    Deliberately NOT a permission code: ctx.permission_codes come from the
    caller's TENANT role, so gating on a "platform_admin" code would be both
    unreachable (nothing seeds a cross-tenant permission) and dangerous — an
    operator granting that code to a tenant role would turn a plain tenant
    user into a cross-tenant admin able to mint break-glass capabilities for
    ANY tenant. The claim cannot be granted per-tenant.
    """
    if not ctx.user.is_platform_admin:
        raise PermissionDeniedError(
            "platform admin access required — this is not a tenant permission"
        )


__all__ = [
    "PageLimit",
    "PageOffset",
    "TenantContext",
    "TenantCtxDep",
    "require_permission",
    "_require_platform_admin",
]
