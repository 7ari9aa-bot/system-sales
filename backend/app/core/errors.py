"""Domain exception hierarchy.

Every domain error carries a stable machine-readable ``code`` and the HTTP
status it should map to at the API edge (see the DomainError handler in
app.main). Callers can catch ``DomainError`` and serialize code / message /
details without knowing the concrete class.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all expected (non-bug) failures."""

    code: str = "domain_error"
    http_status: int = 400
    default_message: str = "Domain error"

    def __init__(
        self, message: str | None = None, *, details: dict[str, Any] | None = None
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Serializable form for API error responses and structured logs."""
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFoundError(DomainError):
    code = "not_found"
    http_status = 404
    default_message = "Resource not found"


class ValidationError(DomainError):
    code = "validation_error"
    http_status = 400
    default_message = "Validation failed"


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


class InsufficientStockError(DomainError):
    code = "insufficient_stock"
    http_status = 409
    default_message = "Insufficient stock"


class CircuitOpenError(DomainError):
    code = "circuit_open"
    http_status = 503
    default_message = "Circuit breaker is open"


class ExternalProviderError(DomainError):
    code = "external_provider_error"
    http_status = 502
    default_message = "External provider error"
