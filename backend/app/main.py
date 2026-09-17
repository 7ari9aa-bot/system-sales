"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import DomainError
from app.core.middleware import RateLimitMiddleware
from app.core.observability import RequestLoggingMiddleware, configure_logging
from app.core.redis import close_redis, get_redis
from app.modules.ai.router import router as ai_router
from app.modules.billing.router import (
    billing_router,
    webhooks_router,
)
from app.modules.billing.router import (
    platform_router as billing_platform_router,
)
from app.modules.catalog.router import router as catalog_router
from app.modules.conversations.router import (
    public_router as conversations_public_router,
)
from app.modules.conversations.router import (
    router as conversations_router,
)
from app.modules.conversations.router import (
    webhook_router as conversations_webhook_router,
)
from app.modules.customers.router import platform_router as platform_router
from app.modules.customers.router import router as customers_router
from app.modules.identity.router import router as identity_router
from app.modules.inventory.router import router as inventory_router
from app.modules.marketing.router import (
    analytics_router,
)
from app.modules.marketing.router import (
    router as marketing_router,
)
from app.modules.orders.router import router as orders_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()
    await close_redis()


def _exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(_: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Sales OS Core API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    configure_logging()
    _exception_handlers(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.include_router(identity_router)
    app.include_router(conversations_router)
    app.include_router(conversations_public_router)
    app.include_router(conversations_webhook_router)
    app.include_router(catalog_router)
    app.include_router(inventory_router)
    app.include_router(orders_router)
    app.include_router(customers_router)
    app.include_router(platform_router)
    app.include_router(billing_platform_router)
    app.include_router(billing_router)
    app.include_router(webhooks_router)
    app.include_router(marketing_router)
    app.include_router(analytics_router)
    app.include_router(ai_router)

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
