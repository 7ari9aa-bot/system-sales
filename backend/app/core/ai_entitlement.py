"""The plan gate every token-spending AI surface declares: ``CanUseAI``.

A tenant whose plan does not include the AI agents can still hold the RBAC codes that open the
assistant's routes, so permission alone is not the answer to "may this shop spend model budget?".
This dependency is that answer, and it is ONE object: the text assistant
(``app/modules/ai/routers/_deps.py``: ``AIEntitledCtx`` / ``AnalyticsAICtx``) and the spoken
assistant (``app/modules/voice/routers/sessions.py``: ``VoiceAICtx``) both declare it, so the same
tenant is refused, at the same status, with the same error body, on both paths.

It lives in ``app/core`` for the reason ``app/core/guardrails.py`` does: it is a cross-cutting
rule both modules must enforce, and importing it from one of them into the other would add a
counted cross-module edge (``tests/test_module_boundaries.py``) while making one module the owner
of the other's gate. Core is the one place both may read without either owning it.

The ``EntitlementService`` import stays inside ``__call__``: billing imports ``app.core``, so a
module-scope import here would close a cycle at load time.
"""

from __future__ import annotations

from app.core.errors import PermissionDeniedError
from app.modules.identity.deps import TenantContext, TenantCtxDep


class require_ai_entitlement:
    """Refuse a surface the tenant's plan does not sell, before it can spend anything.

    The customer auto-reply hook checked ``CanUseAI``; the sales-analysis, SI-chat and voice
    routes did not, so a tenant without the entitlement could still spend model budget through
    them. Keeping this as a class with ``code`` mirrors ``require_permission`` and the approval
    gate, and keeps the gate a route declares introspectable from the outside.
    """

    code = "CanUseAI"

    async def __call__(self, ctx: TenantCtxDep) -> TenantContext:
        from app.modules.billing.services.entitlements import EntitlementService

        if not await EntitlementService.can(ctx.session, ctx.tenant_id, self.code):
            # 403, not 429: a plan-capability gap is PERMANENT until the
            # merchant upgrades — 429's retry semantics made clients back off
            # and retry a surface that can never succeed (deep review).
            raise PermissionDeniedError(
                "plan does not allow AI agents",
                details={"capability": self.code},
            )
        return ctx


__all__ = ["require_ai_entitlement"]
