"""The AI provider request must be routed through a per-ENDPOINT breaker.

`app/core/circuit_breaker.py` was complete and unit-tested but imported by
NOTHING, so a dead or slow AI provider was hammered indefinitely with no
backoff. `AIGateway.chat` is where the chat request is issued; it must go
through the process-wide breaker registry, and an OPEN breaker must surface
as `CircuitOpenError` (HTTP 503, retryable — the unified degradation shape)
rather than being swallowed by the `except Exception` that records a provider
failure as a generic error.

Isolation (package 3.1): the breaker is keyed PER PROVIDER HOST, not one
shared name for the platform. The first version used a single `provider.ai`
breaker for every endpoint, so one tenant's self-hosted endpoint failing
repeatedly opened it and blocked every other tenant's calls to completely
different providers — one bad endpoint became a platform-wide AI outage.
Endpoints that share an upstream host still share a breaker (that IS one
downstream dependency); a dead private endpoint cannot reach across the
network boundary to anyone else.

Deliberately DB-free: the budget reservation and config lookups are stubbed, so
this runs without Postgres locally and unchanged in CI.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.core.circuit_breaker import (
    OPEN,
    PROVIDER_AI,
    get_breaker,
    reset_breakers,
)
from app.core.errors import CircuitOpenError, ExternalProviderError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.gateway import AIGateway

_THRESHOLD = 3

# Two DIFFERENT provider hosts — the isolation boundary under test.
_HOST_A = "api.test"
_HOST_B = "other-provider.test"


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


def _config_for(base_url: str) -> dict:
    return {
        "provider": "openai",
        "model": "gpt-test",
        "base_url": base_url,
        "api_key": "test-key",
    }


def _stub_lookups_for(base_url: str):
    async def _model_config(*args, **kwargs) -> dict:
        return _config_for(base_url)

    def _install(monkeypatch):
        monkeypatch.setattr(ai_gateway, "reserve_budget", _no_reservation)
        monkeypatch.setattr(ai_gateway, "resolve_model_config", _model_config)

    return _install


@pytest.fixture(autouse=True)
def _isolated_breakers(monkeypatch):
    """Fresh registry and a known threshold, so no state leaks in or out."""
    reset_breakers()
    monkeypatch.setattr("app.core.config.get_settings", lambda: _Settings())
    yield
    reset_breakers()


def _failing_provider(requests: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(500, json={"error": "provider down"})

    return handler


def _ok_provider(requests: list[str], content: str = "pong"):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "model": "gpt-test",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    return handler


async def _chat(gateway: AIGateway, session: _Session, client: httpx.AsyncClient):
    return await gateway.chat(
        session,
        uuid4(),
        alias="fast",
        messages=[{"role": "user", "content": "hi"}],
        _client=client,
    )


async def test_open_breaker_stops_calling_the_provider(monkeypatch):
    _stub_lookups_for(f"https://{_HOST_A}/v1")(monkeypatch)
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
        # The breaker that opened is the one for THIS endpoint's host.
        assert get_breaker(f"{PROVIDER_AI}:{_HOST_A}").state == OPEN

        # An open breaker must be visible AS an open breaker, and the provider
        # must not be called again.
        with pytest.raises(CircuitOpenError):
            await _chat(gateway, session, client)

    assert len(requests) == _THRESHOLD
    assert get_breaker(f"{PROVIDER_AI}:{_HOST_A}").is_open


async def test_breaker_is_shared_across_gateway_instances(monkeypatch):
    """One breaker per provider host, not one per gateway — else N calls must fail."""
    _stub_lookups_for(f"https://{_HOST_A}/v1")(monkeypatch)
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


async def test_one_provider_failing_does_not_stop_another(monkeypatch):
    """Package 3.1 isolation: a dead endpoint must be a LOCAL outage.

    The first shared-breaker shape opened `provider.ai` for the whole platform,
    so every tenant's healthy provider was blocked behind one tenant's dead
    endpoint. Here host A trips; host B must still complete its call — same
    process, same registry, different network boundary.
    """
    _stub_lookups_for(f"https://{_HOST_A}/v1")(monkeypatch)
    session = _Session()
    failing: list[str] = []
    healthy: list[str] = []

    # Trip A first: the shared `provider.ai:<A>` breaker opens.
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_failing_provider(failing))
    ) as client:
        for _ in range(_THRESHOLD):
            with pytest.raises(ExternalProviderError):
                await _chat(AIGateway(), session, client)
    assert get_breaker(f"{PROVIDER_AI}:{_HOST_A}").is_open

    # Now point the SAME gateway at a different provider host entirely.
    _stub_lookups_for(f"https://{_HOST_B}/v1")(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_ok_provider(healthy))
    ) as client:
        result = await _chat(AIGateway(), session, client)
    assert result.content == "pong"
    # A stayed backed off; B was never refused by A's breaker.
    assert get_breaker(f"{PROVIDER_AI}:{_HOST_A}").is_open
    assert get_breaker(f"{PROVIDER_AI}:{_HOST_B}").state == "closed"


async def test_circuit_open_is_the_unified_retryable_503(monkeypatch):
    """An open provider breaker degrades to a RETRYABLE 503, never a 500."""
    assert CircuitOpenError.http_status == 503
    assert CircuitOpenError.retryable is True
    _stub_lookups_for(f"https://{_HOST_A}/v1")(monkeypatch)
    session = _Session()
    requests: list[str] = []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_failing_provider(requests))
    ) as client:
        for _ in range(_THRESHOLD):
            with pytest.raises(ExternalProviderError):
                await _chat(AIGateway(), session, client)
        with pytest.raises(CircuitOpenError) as exc_info:
            await _chat(AIGateway(), session, client)
        assert exc_info.value.http_status == 503
        assert exc_info.value.retryable is True


async def test_half_open_recovery_is_gradual(monkeypatch):
    """After the recovery window the breaker admits a probe; success closes,
    failure re-opens — per endpoint, with a controllable clock."""
    clock = [0.0]

    class _TimedSettings(_Settings):
        pass

    breaker = get_breaker(f"{PROVIDER_AI}:{_HOST_A}", time_fn=lambda: clock[0])
    assert breaker.name == f"{PROVIDER_AI}:{_HOST_A}"

    _stub_lookups_for(f"https://{_HOST_A}/v1")(monkeypatch)
    session = _Session()
    requests: list[str] = []

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_failing_provider(requests))
    ) as client:
        for _ in range(_THRESHOLD):
            with pytest.raises(ExternalProviderError):
                await _chat(AIGateway(), session, client)
        assert breaker.state == OPEN
        with pytest.raises(CircuitOpenError):
            await _chat(AIGateway(), session, client)

        # Advance past the recovery timeout: the next call is the probe.
        clock[0] += 31.0
        # Still failing → the probe re-opens the breaker with a fresh timer.
        with pytest.raises(ExternalProviderError):
            await _chat(AIGateway(), session, client)
        assert breaker.state == OPEN

        # Advance again; now the provider is healthy. One success closes the
        # breaker (half_open_successes=1 in the test settings).
        clock[0] += 31.0
        healthy: list[str] = []
        client_ok = httpx.AsyncClient(transport=httpx.MockTransport(_ok_provider(healthy)))
        try:
            result = await _chat(AIGateway(), session, client_ok)
        finally:
            await client_ok.aclose()
        assert result.content == "pong"
        assert breaker.state == "closed"

        # Closed means normal operation resumes: further calls go through.
        healthy.clear()
        client_ok2 = httpx.AsyncClient(transport=httpx.MockTransport(_ok_provider(healthy)))
        try:
            result = await _chat(AIGateway(), session, client_ok2)
        finally:
            await client_ok2.aclose()
        assert result.content == "pong"
        assert len(healthy) == 1
