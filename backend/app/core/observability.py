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

from app.core.errors import request_id_contextvar

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
        logger.info("otel.initialized service=%s endpoint=%s", service_name, endpoint)
    except ImportError:
        logger.info("otel.sdk_not_installed — traces disabled (local/dev mode)")
    except Exception as exc:  # noqa: BLE001 — OTEL must not crash the app
        logger.warning("otel.init_failed error=%s: %s", type(exc).__name__, exc)


def get_tracer():
    """Return the OpenTelemetry tracer, or None if not configured."""
    if not _otel_initialized:
        _try_init_otel()
    return _tracer


def _add_request_id(_logger, _method, event_dict: dict) -> dict:
    """The id of the request being served, on every line, whichever logger wrote it.

    The edge middleware publishes it in a contextvar. Lines written through structlog already
    carried it by hand; the standard-library lines (the great majority) carried nothing, so a
    channel failure could not be followed from the request that caused it.
    """
    if "request_id" not in event_dict:
        current = request_id_contextvar.get()
        if current:
            event_dict["request_id"] = current
    return event_dict


def _shared_processors() -> list:
    """What every line gets, from structlog or from the standard library alike.

    The logger NAME is not here: `structlog.stdlib.add_logger_name` needs a standard-library
    logger, and the native structlog chain writes through a PrintLogger that has none. Each chain
    adds its own (see `configure_logging`).
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_id,
    ]


def configure_logging() -> None:
    from app.core.config import get_settings
    from app.core.log_redaction import install_secret_redaction

    level = logging.DEBUG if get_settings().debug else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    # The standard-library lines used to go out as bare text: no level, no time, no request id,
    # and not parseable as JSON next to the structlog lines around them. Give the same handler a
    # JSON formatter. Redaction is a FILTER on that handler and runs before any formatter, so the
    # text this renders is already scrubbed.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.add_logger_name, *_shared_processors()],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
    install_secret_redaction()
    structlog.configure(
        processors=[
            *_shared_processors(),
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


async def _count_failed_request() -> None:
    """Count a request that ended in an unhandled exception.

    `request_failed` was only a log line, so nothing could alert on a rising rate of them. The
    counter carries no label on purpose: a path holds ids, and the exposure rule allows aggregates
    only. A metrics outage must never make a failed request worse, so this never raises.
    """
    try:
        from app.core.metrics import increment

        await increment("http_requests_failed_total", strict=False)
    except Exception:  # noqa: BLE001 - counting is never worth a second failure
        logger.debug("metrics.http_failed_count_failed", exc_info=True)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Adds a request id + emits one structured log line per request.

    §84: also creates an OpenTelemetry span for each request (when the SDK
    is configured). The span name is "{method} {path_template}" and carries
    the request_id, status_code, and duration_ms as attributes.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # The id published by app.main._RequestIDMiddleware, when that middleware
        # is in the stack. Minting a second one here is how the response header
        # and the error body's ``request_id`` ended up naming two different
        # requests (P5); the edge sanitizer is also the only place that decides
        # whether a client-supplied id is trustworthy enough to echo.
        request_id = (
            request_id_contextvar.get()
            or request.headers.get("x-request-id")
            or uuid.uuid4().hex[:16]
        )
        started = time.perf_counter()

        # §84: create an OTEL span if the tracer is available
        tracer = get_tracer()
        span_cm = None
        if tracer is not None:
            span_cm = tracer.start_as_current_span(f"{request.method} {request.url.path}")
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
            await _count_failed_request()
            if span_cm is not None:
                _span = tracer  # type: ignore[assignment]
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
