"""Observability: structlog configuration + request logging middleware.

Production adds OpenTelemetry via env (OTEL_EXPORTER_OTLP_ENDPOINT) — the SDK
is optional at runtime so local/dev stays dependency-light.
"""

from __future__ import annotations

import logging
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


def configure_logging() -> None:
    from app.core.config import get_settings

    level = logging.DEBUG if get_settings().debug else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Adds a request id + emits one structured log line per request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            get_logger("http").error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                request_id=request_id,
            )
            raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        get_logger("http").info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response
