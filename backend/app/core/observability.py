"""Observability: structlog configuration + request logging middleware.

Production adds OpenTelemetry via env (OTEL_EXPORTER_OTLP_ENDPOINT) — the SDK
is optional at runtime so local/dev stays dependency-light.

§83-84: OpenTelemetry traces are exported to an OTLP endpoint when configured.
The tracer is used by the request middleware to create spans for each HTTP
request, and by the AI gateway to create spans for each provider call.
"""

from __future__ import annotations

import logging
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# OpenTelemetry is optional at runtime. The import is inside a try block
# so the app works without opentelemetry-sdk installed (local/dev).
_tracer = None
_otel_initialized = False


def _try_init_otel() -> None:
    """§84: initialize OpenTelemetry SDK if the env var is set and the package is installed."""
    global _tracer, _otel_initialized
    if _otel_initialized:
        return
    _otel_initialized = True

    import os

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name = os.environ.get("OTEL_SERVICE_NAME", "sales-os-backend")
    if not endpoint:
        return  # no endpoint configured — stay with structlog only

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(__name__)
        logger.info(
            "otel.initialized service=%s endpoint=%s", service_name, endpoint
        )
    except ImportError:
        logger.info("otel.sdk_not_installed — traces disabled (local/dev mode)")
    except Exception as exc:  # noqa: BLE001 — OTEL must not crash the app
        logger.warning("otel.init_failed error=%s: %s", type(exc).__name__, exc)


def get_tracer():
    """Return the OpenTelemetry tracer, or None if not configured."""
    if not _otel_initialized:
        _try_init_otel()
    return _tracer


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
    # §84: initialize OTEL if configured
    _try_init_otel()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Adds a request id + emits one structured log line per request.

    §84: also creates an OpenTelemetry span for each request (when the SDK
    is configured). The span name is "{method} {path_template}" and carries
    the request_id, status_code, and duration_ms as attributes.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()

        # §84: create an OTEL span if the tracer is available
        tracer = get_tracer()
        span_cm = None
        if tracer is not None:
            span_cm = tracer.start_as_current_span(
                f"{request.method} {request.url.path}"
            )
            span_cm.__enter__()

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
            if span_cm is not None:
                span = tracer  # type: ignore[assignment]
                from opentelemetry import trace as otel_trace
                span_obj = otel_trace.get_current_span()
                if span_obj:
                    span_obj.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR))
                    span_obj.set_attribute("request_id", request_id)
                    span_obj.set_attribute("duration_ms", duration_ms)
                span_cm.__exit__(None, None, None)
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
        if span_cm is not None:
            from opentelemetry import trace as otel_trace
            span_obj = otel_trace.get_current_span()
            if span_obj:
                span_obj.set_attribute("request_id", request_id)
                span_obj.set_attribute("http.status_code", response.status_code)
                span_obj.set_attribute("duration_ms", duration_ms)
            span_cm.__exit__(None, None, None)
        return response
