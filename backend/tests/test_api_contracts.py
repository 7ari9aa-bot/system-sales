"""Wave 1 API contract tests — /api/v1 mount, unified error body, cursors.

These are DB-free unit/HTTP tests: cursor codec round-trips, the unified
error contract, and route mounting. No database is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import (
    CircuitOpenError,
    DomainError,
    NotFoundError,
    ValidationError,
    build_error_body,
    request_id_contextvar,
)
from app.core.pagination import decode_cursor, encode_cursor, page_slice
from app.main import create_app


@pytest.fixture()
def app():
    return create_app()


# ------------------------------------------------------------ cursors ----


def test_cursor_round_trip() -> None:
    created_at = datetime(2026, 9, 18, 12, 30, 15, tzinfo=UTC)
    row_id = uuid4()

    cursor = encode_cursor(created_at, row_id)

    assert isinstance(cursor, str)
    assert decode_cursor(cursor) == (created_at, row_id)


def test_cursor_round_trip_naive_datetime() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5)
    row_id = uuid4()

    assert decode_cursor(encode_cursor(created_at, row_id)) == (created_at, row_id)


@pytest.mark.parametrize(
    "bad_cursor",
    [
        "not-a-cursor",  # invalid base64
        "aGVsbG8",  # base64 of "hello" — not JSON
        "e30",  # base64 of "{}" — missing keys
        "eyJjcmVhdGVkX2F0IjogIjIwMjYtMDEtMDFUMDA6MDA6MDAifQ",  # missing id
        "eyJjcmVhdGVkX2F0IjogIm5vdC1hLWRhdGUiLCAiaWQiOiAibm90LWEtdXVpZCJ9",  # bad values
    ],
)
def test_invalid_cursor_raises_validation_error(bad_cursor: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        decode_cursor(bad_cursor)
    assert exc_info.value.code == "invalid_cursor"


def test_page_slice_returns_cursor_only_when_full() -> None:
    class Row:
        def __init__(self, n: int) -> None:
            self.created_at = datetime(2026, 9, 18, 0, 0, n, tzinfo=UTC)
            self.id = uuid4()

    rows = [Row(i) for i in range(5)]

    page, next_cursor = page_slice(rows[:4], 3)  # limit+1 fetched → full page
    assert len(page) == 3
    assert next_cursor == encode_cursor(page[-1].created_at, page[-1].id)

    page, next_cursor = page_slice(rows[:2], 3)  # short page — end of list
    assert len(page) == 2
    assert next_cursor is None


# ------------------------------------------------------ error contract ----


def test_domain_error_retryable_defaults_and_override() -> None:
    assert DomainError().retryable is False
    assert NotFoundError("gone").retryable is False
    # transient failures
    assert CircuitOpenError().retryable is True
    assert NotFoundError("blip", retryable=True).retryable is True
    assert DomainError(retryable=False).retryable is False


def test_build_error_body_unified_contract() -> None:
    exc = NotFoundError("missing", details={"id": "1"})

    body = build_error_body(exc, request_id="req-123")
    assert body == {
        "error": {
            "code": "not_found",
            "message": "missing",
            "retryable": False,
            "request_id": "req-123",
        }
    }

    assert build_error_body(exc)["error"]["request_id"] is None


def test_request_id_contextvar_defaults_to_none() -> None:
    assert request_id_contextvar.get() is None


# ------------------------------------------------------- route mounting ----


def _openapi_paths(app) -> set[str]:
    """FastAPI >=0.121 includes routers lazily; the OpenAPI schema is the
    flattened, externally visible route contract."""
    return set(app.openapi()["paths"])


def test_api_v1_prefix_mounted(app) -> None:
    paths = _openapi_paths(app)

    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/orders" in paths
    assert "/api/v1/customers" in paths
    assert "/api/v1/conversations" in paths
    assert "/api/v1/marketing/campaigns" in paths
    assert "/api/v1/ai/knowledge" in paths


def test_health_probes_stay_at_root(app) -> None:
    paths = _openapi_paths(app)

    assert "/healthz" in paths
    assert "/readyz" in paths
    assert "/api/v1/healthz" not in paths
    assert "/api/v1/readyz" not in paths


async def test_domain_error_response_uses_unified_contract(app) -> None:
    """An unknown webhook channel raises NotFoundError before touching the DB;
    the rendered body must follow the unified error contract."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/webhooks/definitely-not-a-channel",
            headers={"x-request-id": "test-req-id"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"] == "test-req-id"
    assert body["error"]["message"]
