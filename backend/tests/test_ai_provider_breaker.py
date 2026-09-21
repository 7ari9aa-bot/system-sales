"""The AI provider request must be routed through the shared circuit breaker.

`app/core/circuit_breaker.py` was complete and unit-tested but imported by
NOTHING, so a dead or slow AI provider was hammered indefinitely with no
backoff. `AIGateway.chat` is where the chat request is issued; it must go
through the process-wide `provider.ai` breaker, and an OPEN breaker must surface
as `CircuitOpenError` rather than being swallowed by the `except Exception` that
records a provider failure as a generic error.

Deliberately DB-free: the budget reservation and config lookups are stubbed, so
this runs without Postgres locally and unchanged in CI.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.core.circuit_breaker import OPEN, PROVIDER_AI, get_breaker, reset_breakers
from app.core.errors import CircuitOpenError, ExternalProviderError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.gateway import AIGateway

_THRESHOLD = 3


class _Settings:
    """Only the fields `get_breaker` reads."""

    circuit_breaker_failure_threshold = _THRESHOLD
    circuit_breaker_recovery_seconds = 30.0
    circuit_breaker_half_open_successes = 1


class _Session:
    """Minimal stand-in for AsyncSession — the gateway only adds and flushes."""

    def __init__(self) -> None:
        self.rows: list = []

    def add(self, row) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        return None

    async def execute(self, *_args, **_kwargs):
        """Minimal execute stub — returns a result with scalar_one_or_none()."""

        class _Result:
            def scalar_one_or_none(self):
                return None

        return _Result()


async def _no_reservation(*args, **kwargs):
    return None


async def _model_config(*args, **kwargs) -> dict:
    return {
        "provider": "openai",
        "model": "gpt-test",
        "base_url": "https://api.test/v1",
        "api_key": "test-key",
    }


@pytest.fixture(autouse=True)
def _isolated_breakers(monkeypatch):
    """Fresh registry and a known threshold, so no state leaks in or out."""
    reset_breakers()
    monkeypatch.setattr("app.core.config.get_settings", lambda: _Settings())
    yield
    reset_breakers()


@pytest.fixture
def _stub_lookups(monkeypatch):
    monkeypatch.setattr(ai_gateway, "reserve_budget", _no_reservation)
    monkeypatch.setattr(ai_gateway, "resolve_model_config", _model_config)


def _failing_provider(requests: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(500, json={"error": "provider down"})

    return handler


async def _chat(gateway: AIGateway, session: _Session, client: httpx.AsyncClient):
    return await gateway.chat(
        session,
        uuid4(),
        alias="fast",
        messages=[{"role": "user", "content": "hi"}],
        _client=client,
    )


async def test_open_breaker_stops_calling_the_provider(_stub_lookups):
    gateway = AIGateway()
    session = _Session()
    requests: list[str] = []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_failing_provider(requests))
    ) as client:
        for _ in range(_THRESHOLD):
            with pytest.raises(ExternalProviderError):
                await _chat(gateway, session, client)
        assert len(requests) == _THRESHOLD
        assert get_breaker(PROVIDER_AI).state == OPEN

        # An open breaker must be visible AS an open breaker, and the provider
        # must not be called again.
        with pytest.raises(CircuitOpenError):
            await _chat(gateway, session, client)

    assert len(requests) == _THRESHOLD
    assert get_breaker(PROVIDER_AI).is_open


async def test_breaker_is_shared_across_gateway_instances(_stub_lookups):
    """One breaker per provider, not one per gateway — else N calls must fail."""
    session = _Session()
    requests: list[str] = []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_failing_provider(requests))
    ) as client:
        for _ in range(_THRESHOLD):
            with pytest.raises(ExternalProviderError):
                await _chat(AIGateway(), session, client)

        with pytest.raises(CircuitOpenError):
            await _chat(AIGateway(), session, client)

    assert len(requests) == _THRESHOLD
