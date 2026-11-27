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

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.modules.applications.access import AccessFacts, decide_access
from app.modules.applications.manifests import get_manifest


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
