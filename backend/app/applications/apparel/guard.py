"""The gate an apparel route asks for.

Three questions, in this order, and never fewer: does this workspace run the
apparel application, does the licence allow it, and does this user hold the
apparel permission the endpoint serves. The platform gate answers the first two;
this module adds the third and keeps the answer in one object, so a handler
receives a verified context instead of assembling one from request fields
(industry-applications §16).

Read-only is a real state, not a note: a workspace whose licence lapsed to
read-only can still open its reports, and can still export them, because the
data is the owner's; it cannot post a sale.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from app.applications.apparel.compat import satisfied_by_legacy
from app.applications.apparel.lifecycle import allows_reads, allows_writes
from app.applications.apparel.manifest import APP_MANIFEST
from app.applications.apparel.permissions import get_permission, is_write_code
from app.core.config import get_settings
from app.core.context import application_key_contextvar
from app.core.errors import PermissionDeniedError
from app.modules.applications.access import decide_access
from app.modules.applications.repository import gather_facts

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module importable alone
    from app.modules.identity.deps import TenantContext

logger = logging.getLogger(__name__)

#: The commercial key the licence is sold under today. The sector application is
#: one product; the billing catalogue still names it ``retail.core`` until the
#: rename in decision D1 lands, and this constant is the only place that knows.
APPAREL_LICENCE_KEY = "retail.core"

#: No installation rows at all: the workspace predates the gate. Same transition
#: rule the platform gate applies, stated once here so the two cannot disagree.
UNCONFIGURED = "__unconfigured__"


@dataclass(frozen=True, slots=True)
class ApparelAccess:
    """A verified apparel request: who, where, and what they may do."""

    tenant_id: object
    workspace_id: object
    user_id: object
    permission_code: str
    installation_state: str
    read_only: bool


def is_write(permission_code: str) -> bool:
    """Does this permission change data? One rule, defined with the codes."""
    return is_write_code(permission_code)


def decide_apparel_access(
    *,
    tenant_id: object,
    workspace_id: object,
    user_id: object,
    permission_code: str,
    held_codes: frozenset[str] | set[str],
    installation_state: str,
) -> ApparelAccess:
    """The decision, with no database and no FastAPI in the way.

    Every refusal names what is missing, because "forbidden" with no reason is
    how a support ticket starts.
    """
    get_permission(permission_code)  # unknown code is a bug, not a refusal

    if tenant_id is None:
        raise PermissionDeniedError("no tenant on this request")
    if workspace_id is None:
        raise PermissionDeniedError(
            "no workspace on this request: apparel needs an active business"
        )
    if user_id is None:
        raise PermissionDeniedError("no user on this request")

    # One lifecycle, one answer: an unconfigured workspace keeps the platform's
    # transition rule, and any other state is judged by lifecycle.py, which
    # refuses states it does not know.
    if installation_state != UNCONFIGURED and not allows_reads(installation_state):
        raise PermissionDeniedError(f"apparel is {installation_state} for this workspace")

    # The apparel code first, then the legacy code it replaces while roles are
    # still platform-era (see compat.py: the bridge is temporary and directional).
    if permission_code not in held_codes and not satisfied_by_legacy(permission_code, held_codes):
        raise PermissionDeniedError(f"missing permission: {permission_code}")

    read_only = installation_state != UNCONFIGURED and not allows_writes(installation_state)
    if read_only and is_write(permission_code):
        raise PermissionDeniedError("apparel is read only: this action changes data")

    # Every log line, audit row and job enqueued from here on says which
    # application it belongs to (18), without the platform knowing the name.
    application_key_contextvar.set(APP_MANIFEST.key)

    return ApparelAccess(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
        permission_code=permission_code,
        installation_state=installation_state,
        read_only=read_only,
    )


async def apparel_access(ctx: TenantContext, permission_code: str) -> ApparelAccess:
    """Resolve the licence facts for this request, then decide.

    The licence check reuses the platform's own decision instead of repeating
    its rules here: an entitlement or installation bug must have exactly one
    place to be fixed.
    """
    state = UNCONFIGURED
    if getattr(ctx, "session", None) is not None:
        facts = await gather_facts(
            ctx.session,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            application_key=APPAREL_LICENCE_KEY,
        )
        if facts.installation_states:
            decision = decide_access(replace(facts, application_key=APPAREL_LICENCE_KEY))
            if not decision.allowed:
                raise PermissionDeniedError(decision.reason)
            state = facts.installation_states.get(APPAREL_LICENCE_KEY) or UNCONFIGURED
        else:
            logger.warning(
                "apparel gate: workspace has no installations, licence not enforced",
                extra={
                    "workspace_id": str(ctx.workspace_id),
                    "tenant_id": str(ctx.tenant_id),
                },
            )

    return decide_apparel_access(
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        user_id=getattr(ctx.user, "id", None),
        permission_code=permission_code,
        held_codes=getattr(ctx, "permission_codes", set()),
        installation_state=state,
    )


def require_apparel(permission_code: str) -> Callable[..., object]:
    """Build the dependency a route declares.

    ``Depends(require_apparel("apparel.pos.sell"))`` reads as what it is, and an
    unknown code fails at import time instead of at the first sale.
    """
    get_permission(permission_code)

    # Imported here so this module can be imported, and its decision tested, in a
    # process that has no web stack and no database.
    from fastapi import Depends

    from app.modules.identity.deps import get_tenant_ctx

    async def dependency(ctx: TenantContext = Depends(get_tenant_ctx)) -> ApparelAccess | None:
        mode = getattr(get_settings(), "apparel_gate_mode", "shadow")
        if mode == "off":
            return None
        try:
            return await apparel_access(ctx, permission_code)
        except PermissionDeniedError as exc:
            if mode == "enforce":
                raise
            # Shadow: the decision is recorded so it can be read before it is
            # trusted. A gate nobody has watched is a gate that breaks a shop.
            logger.warning(
                "apparel gate (shadow) would deny %s: %s",
                permission_code,
                exc.message,
                extra={
                    "workspace_id": str(getattr(ctx, "workspace_id", "")),
                    "tenant_id": str(getattr(ctx, "tenant_id", "")),
                    "permission_code": permission_code,
                },
            )
            return None

    dependency.__name__ = f"require_apparel_{permission_code.replace('.', '_')}"
    return dependency
