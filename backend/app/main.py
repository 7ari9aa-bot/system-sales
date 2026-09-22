"""FastAPI application factory.

All domain routes are versioned under ``/api/v1`` (breaking W1 contract);
operational probes (/healthz, /readyz) stay at the root for load balancers.
"""

from __future__ import annotations

import hmac
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.context import actor_kind_contextvar, credentials_audit_contextvar
from app.core.db import engine
from app.core.errors import (
    DomainError,
    PermissionDeniedError,
    build_error_body,
    correlation_id_contextvar,
    request_id_contextvar,
)
from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.observability import RequestLoggingMiddleware, configure_logging
from app.core.redis import close_redis, get_redis
from app.modules.ai.router import router as ai_router
from app.modules.analytics.router import router as analytics_module_router
from app.modules.automation.router import router as automation_router
from app.modules.billing.router import (
    billing_router,
    webhooks_router,
)
from app.modules.catalog.router import router as catalog_router
from app.modules.conversations.router import (
    public_router as conversations_public_router,
)
from app.modules.conversations.router import (
    router as conversations_router,
)
from app.modules.conversations.router import (
    templates_router as conversations_templates_router,
)
from app.modules.conversations.router import (
    webhook_router as conversations_webhook_router,
)
from app.modules.customers.router import platform_router as platform_router
from app.modules.customers.router import router as customers_router
from app.modules.identity.router import hierarchy_router as identity_hierarchy_router
from app.modules.identity.router import router as identity_router
from app.modules.identity.router import tenants_router as identity_tenants_router
from app.modules.identity.router import users_router as identity_users_router
from app.modules.inventory.router import router as inventory_router
from app.modules.marketing.router import (
    analytics_router,
)
from app.modules.marketing.router import (
    router as marketing_router,
)
from app.modules.notifications.router import router as notifications_router
from app.modules.operations.router import (
    router as operations_router,
)
from app.modules.operations.router import (
    search_router as operations_search_router,
)
from app.modules.operations.router import (
    sla_router as operations_sla_router,
)
from app.modules.orders.router import router as orders_router
from app.modules.platform.router import router as platform_module_router
from app.modules.privacy.router import router as privacy_router
from app.modules.realtime.router import router as realtime_router
from app.modules.segments.router import router as segments_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # G-06: a secure environment must never serve secrets from process memory
    # (EnvSecretStore is per-process os.environ — unshared across workers and
    # lost on restart). get_secret_store() resolves DatabaseSecretStore there
    # by default; this catches a mistaken set_secret_store() override at boot
    # rather than at first secret read.
    from app.core.secrets import EnvSecretStore, get_secret_store

    if get_settings().is_secure_environment and isinstance(
        get_secret_store(), EnvSecretStore
    ):
        raise RuntimeError(
            "secure environment resolved EnvSecretStore — secret values would be "
            "process-local and lost on restart; refusing to boot"
        )
    yield
    await engine.dispose()
    await close_redis()


class _RequestIDMiddleware:
    """Publishes the request id into a contextvar for the error contract.

    Honors an incoming ``x-request-id`` (or generates one); the same id is
    echoed by the unified error body's ``request_id`` field.
    """

    def __init__(self, app) -> None:  # ASGI app signature
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # ASGI signature
        if scope["type"] != "http":  # pragma: no cover — lifespan etc.
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        request_id = _trusted_trace_id(headers.get("x-request-id")) or uuid.uuid4().hex[:16]
        # §65: correlation_id links HTTP requests to domain events. Honored
        # from x-correlation-id (for cross-service tracing) or generated fresh.
        # Passed to add_outbox_event so every event traces back to its cause.
        correlation_id = (
            _trusted_trace_id(headers.get("x-correlation-id")) or uuid.uuid4().hex[:16]
        )
        req_token = request_id_contextvar.set(request_id)
        cor_token = correlation_id_contextvar.set(correlation_id)
        # §66: actor kind for the audit source column — an internal service
        # token (n8n -> core) marks the request "automation", everything else
        # is a "human" request. Workers set their own kind outside HTTP. This
        # is a label for audit lineage, NOT an auth check (that lives in deps).
        service_token = get_settings().service_token_internal
        actor_kind = "automation" if _presents_service_token(headers, service_token) else "human"
        kind_token = actor_kind_contextvar.set(actor_kind)
        # §68: fresh per-request batch set for credential-read auditing.
        audit_token = credentials_audit_contextvar.set(set())
        try:
            await self.app(scope, receive, send)
        finally:
            request_id_contextvar.reset(req_token)
            correlation_id_contextvar.reset(cor_token)
            actor_kind_contextvar.reset(kind_token)
            credentials_audit_contextvar.reset(audit_token)


# §66: audit_logs.request_id / correlation_id are String(64); client-supplied
# ids must fit that shape or they break the INSERT and pollute the trail.
_TRACE_ID_MAX = 64
_TRACE_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _trusted_trace_id(raw: str | None) -> str | None:
    """Return a client-supplied request/correlation id only if it is plausible.

    Anything else (too long, weird charset, empty) is ignored — the caller
    falls back to a freshly generated id. Honoring arbitrary client content in
    durable lineage columns is not free: it is a stored-value attack surface.
    """
    if raw and _TRACE_ID_RE.fullmatch(raw):
        return raw
    return None


def _presents_service_token(headers: dict[str, str], service_token: str | None) -> bool:
    """True when Authorization carries the internal service token (§66 label).

    Constant-time digest comparison on the token itself (m11: a lowercase
    string compare both leaked timing and case-collapsed the credential);
    only the ``Bearer`` scheme keyword is case-insensitive, per RFC 9110.
    """
    if not service_token:
        return False
    authorization = headers.get("authorization", "")
    scheme, _, presented = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(presented, service_token)


def _exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=build_error_body(exc, request_id=request_id_contextvar.get()),
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_: Request, exc: PermissionError) -> JSONResponse:
        error = PermissionDeniedError(str(exc))
        return JSONResponse(
            status_code=error.http_status,
            content=build_error_body(error, request_id=request_id_contextvar.get()),
        )


def create_app() -> FastAPI:
    settings = get_settings()
    # Production exposes NO schema surface: /docs was already off, but
    # /openapi.json stayed readable and published the entire API surface
    # (every route, parameter and model) to anonymous callers.
    _expose_schema = settings.environment != "production"
    app = FastAPI(
        title="Sales OS Core API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if _expose_schema else None,
        openapi_url="/openapi.json" if _expose_schema else None,
        redoc_url=None,
    )

    configure_logging()
    _exception_handlers(app)
    # Starlette builds the stack so the LAST added middleware is the OUTERMOST.
    # Order below therefore reads inner -> outer:
    #   Idempotency -> RequestLogging -> RateLimit -> BodySize -> RequestID
    #   -> CORS -> SecurityHeaders
    # Idempotency is INNERMOST on purpose: the body cap must reject an oversized
    # body before the idempotency layer buffers it to hash it, and a replayed
    # response still passes back out through CORS and SecurityHeaders. CORS must
    # sit OUTSIDE both the rate limiter and the body cap, or their 429/413
    # responses reach the browser without Access-Control-Allow-Origin (an
    # opaque CORS failure instead of a readable error) — and preflight OPTIONS
    # must short-circuit before they consume the rate budget (P6). RequestID
    # sits OUTSIDE the body cap so its 413 (emitted before any route runs) still
    # carries the request id the unified error contract promises.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(_RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)

    api_v1 = APIRouter(prefix="/api/v1")
    for router in (
        identity_router,
        identity_users_router,
        identity_tenants_router,
        identity_hierarchy_router,
        conversations_router,
        conversations_templates_router,
        conversations_public_router,
        conversations_webhook_router,
        catalog_router,
        inventory_router,
        orders_router,
        customers_router,
        platform_router,
        billing_router,
        webhooks_router,
        marketing_router,
        analytics_router,
        ai_router,
        operations_router,
        operations_search_router,
        operations_sla_router,
        realtime_router,
        notifications_router,
        privacy_router,
        platform_module_router,
        segments_router,
        automation_router,
        analytics_module_router,
    ):
        api_v1.include_router(router)
    app.include_router(api_v1)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"down: {exc.__class__.__name__}"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"down: {exc.__class__.__name__}"
        ready = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, "checks": checks},
        )

    return app


app = create_app()
