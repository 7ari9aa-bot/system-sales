"""Domain error hierarchy contract tests."""

from __future__ import annotations

import pytest

from app.core.errors import (
    CircuitOpenError,
    ConflictError,
    DomainError,
    ExternalProviderError,
    InsufficientStockError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitExceededError,
    ValidationError,
)

CASES = [
    (NotFoundError, "not_found", 404),
    (ValidationError, "validation_error", 400),
    (ConflictError, "conflict", 409),
    (PermissionDeniedError, "permission_denied", 403),
    (RateLimitExceededError, "rate_limit_exceeded", 429),
    (InsufficientStockError, "insufficient_stock", 409),
    (CircuitOpenError, "circuit_open", 503),
    (ExternalProviderError, "external_provider_error", 502),
]


@pytest.mark.parametrize(("error_cls", "code", "http_status"), CASES)
def test_error_contract(error_cls: type[DomainError], code: str, http_status: int) -> None:
    err = error_cls("something broke", details={"key": "value"})

    assert isinstance(err, Exception)
    assert isinstance(err, DomainError)
    assert err.code == code
    assert err.http_status == http_status
    assert err.message == "something broke"
    assert str(err) == "something broke"
    assert err.details == {"key": "value"}


def test_base_defaults() -> None:
    err = DomainError()
    assert err.code == "domain_error"
    assert err.http_status == 400
    assert err.message  # non-empty default message
    assert err.details == {}


def test_details_default_to_empty_and_message_defaults_apply() -> None:
    assert NotFoundError("nope").details == {}
    assert ConflictError().message  # each subclass carries a default message
    assert RateLimitExceededError("slow down", details={"retry_after": 1}).details == {
        "retry_after": 1
    }


def test_catchable_as_domain_error() -> None:
    with pytest.raises(DomainError):
        raise InsufficientStockError("only 3 left", details={"sku": "x", "available": 3})
