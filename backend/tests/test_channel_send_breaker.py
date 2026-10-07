"""WS-A2 — WhatsApp and Telegram sends go through the circuit breaker.

`app/core/circuit_breaker.py` was complete and unit-tested but imported by
NOTHING, so a dead channel provider was hammered on every outbound send with no
back-off at all. Both adapters now route their ONE outbound HTTP request through
the process-wide `provider.whatsapp` / `provider.telegram` breaker, so once the
breaker is OPEN the provider is not contacted and `CircuitOpenError` surfaces
instead of a generic provider error.

The registry is per-PROVIDER, not per-call-site: all WhatsApp sends spend the
same breaker, and a WhatsApp outage must not open the Telegram breaker.

DB-free: the adapters are driven through `httpx.MockTransport`, so this runs
without Postgres locally and unchanged in CI.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.core.circuit_breaker import (
    PROVIDER_TELEGRAM,
    PROVIDER_WHATSAPP,
    get_breaker,
    reset_breakers,
)
from app.core.errors import CircuitOpenError, ExternalProviderError
from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.telegram import telegram_adapter
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter

_THRESHOLD = 2


class _Settings:
    """Only the fields `get_breaker` reads."""

    circuit_breaker_failure_threshold = _THRESHOLD
    circuit_breaker_recovery_seconds = 30.0
    circuit_breaker_half_open_successes = 1


@pytest.fixture(autouse=True)
def _isolated_breakers(monkeypatch):
    """The registry is process-wide, so one case must not leak state into the next."""
    reset_breakers()
    monkeypatch.setattr("app.core.config.get_settings", lambda: _Settings())
    yield
    reset_breakers()


async def _boom() -> None:
    raise RuntimeError("provider down")


async def _trip(name: str) -> None:
    """Open the named breaker and assert it really is OPEN."""
    breaker = get_breaker(name)
    for _ in range(_THRESHOLD):
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
    assert breaker.is_open


def _outbound() -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201234567890",
        body="hello",
    )


def _direct_credentials() -> ProviderCredentials:
    return ProviderCredentials(config={"phone_number_id": "P", "access_token": "T"})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _counting(counter: dict) -> httpx.AsyncClient:
    """A client that records how often the provider was actually contacted."""

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(200, json={"messages": [{"id": "wamid.out1"}]})

    return _client(handler)


def _unreachable() -> httpx.AsyncClient:
    """A transport-level failure: the provider cannot be reached at all."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return _client(handler)


def _failing() -> httpx.AsyncClient:
    """The provider is REACHABLE but rejects the send (HTTP 500)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "description": "provider error"})

    return _client(handler)


# ---------------------------------------------------------------- WhatsApp ---


async def test_whatsapp_send_is_refused_while_the_breaker_is_open() -> None:
    contacted = {"n": 0}
    await _trip(PROVIDER_WHATSAPP)

    with pytest.raises(CircuitOpenError):
        await whatsapp_adapter.send(
            _direct_credentials(), _outbound(), _client=_counting(contacted)
        )

    assert contacted["n"] == 0  # an OPEN breaker means the provider is not contacted


async def test_a_failing_whatsapp_send_trips_the_breaker() -> None:
    """Failures out of the wrapped request are accounted against the breaker."""
    breaker = get_breaker(PROVIDER_WHATSAPP)

    for _ in range(_THRESHOLD):
        with pytest.raises(httpx.ConnectError):
            await whatsapp_adapter.send(_direct_credentials(), _outbound(), _client=_unreachable())

    assert breaker.is_open


async def test_a_rejecting_whatsapp_send_trips_the_breaker() -> None:
    """A provider that is REACHABLE but answers 500 is the case the breaker exists for.

    This was broken at every call site: the breaker wrapped only the HTTP request, and
    the `status_code >= 400` check that raises sat outside it — so a provider rejecting
    every send was recorded as a SUCCESS and the breaker never opened.
    """
    breaker = get_breaker(PROVIDER_WHATSAPP)

    for _ in range(_THRESHOLD):
        with pytest.raises(ExternalProviderError):
            await whatsapp_adapter.send(_direct_credentials(), _outbound(), _client=_failing())

    assert breaker.is_open, "a rejecting provider must count against the breaker"


# ---------------------------------------------------------------- Telegram ---


async def test_telegram_send_is_refused_while_the_breaker_is_open() -> None:
    contacted = {"n": 0}
    await _trip(PROVIDER_TELEGRAM)

    with pytest.raises(CircuitOpenError):
        await telegram_adapter.send(
            ProviderCredentials(config={"bot_token": "BOT"}),
            _outbound(),
            _client=_counting(contacted),
        )

    assert contacted["n"] == 0


async def test_a_failing_telegram_send_trips_the_breaker() -> None:
    breaker = get_breaker(PROVIDER_TELEGRAM)

    for _ in range(_THRESHOLD):
        with pytest.raises(ExternalProviderError):
            await telegram_adapter.send(
                ProviderCredentials(config={"bot_token": "BOT"}),
                _outbound(),
                _client=_failing(),
            )

    assert breaker.is_open


async def test_the_two_providers_have_independent_breakers() -> None:
    """A WhatsApp outage must not stop Telegram delivery (names are per provider)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    await _trip(PROVIDER_WHATSAPP)

    provider_id = await telegram_adapter.send(
        ProviderCredentials(config={"bot_token": "BOT"}),
        _outbound(),
        _client=_client(handler),
    )

    assert provider_id == "77"
    assert not get_breaker(PROVIDER_TELEGRAM).is_open
