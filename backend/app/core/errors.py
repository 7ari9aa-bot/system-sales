"""Domain exception hierarchy.

Every domain error carries a stable machine-readable ``code`` and the HTTP
status it should map to at the API edge (see the DomainError handler in
app.main). Callers can catch ``DomainError`` and serialize code / message /
details without knowing the concrete class.

The unified API error contract (v2) is::

    {"error": {"code": ..., "message": ..., "retryable": bool, "request_id": ...}}

built by :func:`build_error_body` (domain errors) and
:func:`build_error_envelope` (failures the framework raises before/around a
route, which carry no ``DomainError``), and rendered by the handlers in app.main.
Every error status the API answers — domain error, permission denial, 404 for
an unmatched path, 413 body cap, 422 validation refusal, 429 rate limit, 500
crash — carries that object, with the same four keys, and its ``request_id`` is
the id the ``x-request-id`` response header echoes.

Two diagnostic keys ride BESIDE the envelope, both deliberately:
``detail`` on a framework-shaped refusal (the structured per-field list a 422
has no other place to live, and what ``frontend/src/lib/api.ts`` falls back to)
and ``tier`` / ``retry_after`` on a 429 (the only way to tell which bucket
denied). They are additive: a client that only reads ``error`` is never wrong.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# Request id published per-request (see app.main middleware); None outside a
# request or when the edge middleware has not run.
request_id_contextvar: ContextVar[str | None] = ContextVar("request_id", default=None)

# §65: correlation id — links HTTP requests to domain events. Generated per
# request (or honored from x-correlation-id header) and passed to
# add_outbox_event so every event traces back to the request that caused it.
correlation_id_contextvar: ContextVar[str | None] = ContextVar(
    "correlation_id", default=None
)


class DomainError(Exception):
    """Base class for all expected (non-bug) failures."""

    code: str = "domain_error"
    http_status: int = 400
    default_message: str = "Domain error"
    # Transient failures (rate limits, circuit open, provider blips) may be
    # retried; set True per-class or per-instance.
    retryable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = dict(details or {})
        # None → inherit the class default; explicit True/False wins.
        self.retryable = self.retryable if retryable is None else retryable
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class NotFoundError(DomainError):
    code = "not_found"
    http_status = 404
    default_message = "Resource not found"


class ValidationError(DomainError):
    code = "validation_error"
    http_status = 400
    default_message = "Validation failed"


class InvalidCursorError(ValidationError):
    """Malformed / expired pagination cursor (subclass of ValidationError)."""

    code = "invalid_cursor"
    default_message = "Invalid pagination cursor"


class ConflictError(DomainError):
    code = "conflict"
    http_status = 409
    default_message = "Conflict"


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    http_status = 403
    default_message = "Permission denied"


class RateLimitExceededError(DomainError):
    code = "rate_limit_exceeded"
    http_status = 429
    default_message = "Rate limit exceeded"
    retryable = True


class InsufficientStockError(DomainError):
    code = "insufficient_stock"
    http_status = 409
    default_message = "Insufficient stock"


class CircuitOpenError(DomainError):
    code = "circuit_open"
    http_status = 503
    default_message = "Circuit breaker is open"
    retryable = True


class ExternalProviderError(DomainError):
    code = "external_provider_error"
    http_status = 502
    default_message = "External provider error"
    retryable = True


class PayloadTooLargeError(DomainError):
    code = "payload_too_large"
    http_status = 413
    default_message = "Request body too large"


def build_error_envelope(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """The one writer of the v2 envelope's key set.

    Framework-shaped failures (a request that never reached a route, an
    unhandled crash) carry no ``DomainError``, so they build the same body
    through here rather than hand-assembling a fifth shape.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
        }
    }


def build_error_body(
    exc: DomainError, request_id: str | None = None
) -> dict[str, Any]:
    """Unified error contract body: ``{error: {code, message, retryable, request_id}}``."""
    return build_error_envelope(
        exc.code, exc.message, retryable=exc.retryable, request_id=request_id
    )
