"""The gate a route asks for: does this workspace have this application?

``access.decide_access`` is pure and knows nothing about FastAPI. This module is
the seam: it turns a facts provider into a dependency, so a route says
``Depends(require_application("retail.purchasing"))`` and the decision happens in
one place instead of in every handler.

One rule is deliberate and temporary: a workspace with no installation rows at
all is treated as not yet configured and is allowed through. Every account that
exists today has zero rows, so enforcing first would close every paid screen in
production at once. The moment a workspace gets its first installation row, the
gate is real for it — and the row is what onboarding writes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from app.core.errors import PermissionDeniedError
from app.modules.applications.access import AccessFacts, decide_access
from app.modules.applications.manifests import get_manifest
from app.modules.applications.repository import gather_facts

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GateResult:
    """What the route should do, and why — the reason is logged, never shown raw."""

    allowed: bool
    reason: str


def evaluate(
    facts: AccessFacts,
    application_key: str,
    *,
    workspace_configured: bool = True,
) -> GateResult:
    """Decide one application for one workspace.

    ``workspace_configured`` is the transition switch described in the module
    docstring: false means no installations exist yet for this workspace, so the
    gate cannot speak for it and says so in the reason.
    """
    if not workspace_configured:
        return GateResult(True, "workspace_not_configured")
    get_manifest(application_key)  # raises on an unknown key: fail closed
    decision = decide_access(replace(facts, application_key=application_key))
    return GateResult(decision.allowed, decision.reason)


def require_application(
    application_key: str,
    *,
    facts_provider: Callable[[str], AccessFacts] | None = None,
) -> Callable[[], GateResult]:
    """Build the dependency a route declares.

    ``facts_provider`` is injected so the decision can be tested without a
    database; the real provider is wired when the repository lands.
    """
    get_manifest(application_key)  # fail at import time, not at first request

    def dependency() -> GateResult:
        if facts_provider is None:
            raise RuntimeError(
                "application gate has no facts provider yet: wire the repository "
                "before attaching require_application to a route"
            )
        return evaluate(facts_provider(application_key), application_key)

    return dependency


async def workspace_gate(
    application_key: str, ctx, *, product_permission: str | None = None
) -> GateResult:
    """Read the facts for this request's workspace, then judge one application.

    ``product_permission`` is the permission FAMILY this route group serves ("customers",
    not "customers:read"), and it is checked first, before ``gather_facts`` runs its two
    queries. A caller who holds no permission in the family cannot be answered whatever the
    gate says, so the refusal must not cost a database read — `tests/test_customers_http_surface.py`
    asserts exactly that ("the refusal still ran a query"). The family rather than one code,
    because a router serves reads and writes under different codes and only the endpoint
    knows which one it needs; the endpoint's own ``require_permission`` still decides.
    """
    if getattr(ctx, "session", None) is None:
        # No session on this context, so there are no facts to read and no honest way to
        # decide. Every workspace is unconfigured today anyway, so this is the same verdict
        # the query would reach — but it is reached loudly, and it is reached WITHOUT the
        # database, which is what the request-surface tests that build a context by hand
        # assert ("reaching the database would raise"). A context without a session on a
        # real request path is a wiring bug, and this warning is where it shows up.
        logger.warning(
            "application gate has no session on this context: treating the workspace as "
            "unconfigured instead of reading facts",
            extra={
                "application_key": application_key,
                "workspace_id": str(getattr(ctx, "workspace_id", None)),
                "tenant_id": str(getattr(ctx, "tenant_id", None)),
            },
        )
        return evaluate(
            AccessFacts(application_key=application_key),
            application_key,
            workspace_configured=False,
        )
    if product_permission is not None:
        prefix = f"{product_permission}:"
        if not any(
            code == product_permission or code.startswith(prefix)
            for code in getattr(ctx, "permission_codes", set())
        ):
            raise PermissionDeniedError(f"missing permission: {prefix}*")
    facts = await gather_facts(
        ctx.session,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        application_key=application_key,
    )
    if not facts.installation_states:
        # The transition rule has to be loud. Every account today has zero rows, so
        # this line is the only record of which workspaces are still outside the
        # gate - silent, it would look like enforcement that never happened.
        logger.warning(
            "application gate bypassed: workspace has no installations",
            extra={
                "application_key": application_key,
                "workspace_id": str(ctx.workspace_id),
                "tenant_id": str(ctx.tenant_id),
            },
        )
        return evaluate(facts, application_key, workspace_configured=False)
    result = evaluate(facts, application_key)
    if not result.allowed:
        raise PermissionDeniedError(result.reason)
    return result
