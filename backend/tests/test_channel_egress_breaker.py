"""G-13 — EVERY channel provider egress goes through a circuit breaker.

``app/core/circuit_breaker.py`` shipped complete and unit-tested but wired to
only *some* of the outbound providers. WhatsApp, Telegram, the AI gateway and
object storage spent a named breaker; Messenger, Instagram and Email — the other
three channel adapters dispatched from the exact same outbound path
(``message_worker._send`` -> ``adapter.send``) — opened a raw
``httpx.AsyncClient`` and hammered a dead provider on every send and every worker
retry, with no back-off at all.

This file does two things:

1. Behaviour: each newly-wired adapter refuses to contact a dead provider once
   its breaker is OPEN, and a provider that is reachable but REJECTS the send
   (HTTP 5xx) counts against the breaker. The second half is the trap the
   original wiring fell into: wrapping only the HTTP request, and checking the
   status code OUTSIDE ``breaker.call()``, records a rejecting provider as a
   SUCCESS so the breaker never opens — the single case it exists for.
2. Registry-style guard: an AST scan that fails if a named ``PROVIDER_*``
   breaker constant has no caller, or if a gateway adapter module opens an
   ``httpx`` client without routing the call through ``get_breaker``. That way a
   future channel cannot silently re-introduce the hole this pass closed.

DB-free: the adapters are driven through ``httpx.MockTransport``, so this runs
locally and unchanged in CI.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import httpx
import pytest

import app.core.circuit_breaker as cb
from app.core.circuit_breaker import (
    PROVIDER_EMAIL,
    PROVIDER_INSTAGRAM,
    PROVIDER_MESSENGER,
    get_breaker,
    reset_breakers,
)
from app.core.errors import CircuitOpenError, ExternalProviderError
from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.email import email_adapter
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.gateway.messenger import messenger_adapter

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
GATEWAY_DIR = BACKEND_ROOT / "app" / "modules" / "conversations" / "gateway"

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
        customer_ref="customer-1",
        body="hello",
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _counting(counter: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(200, json={"message_id": "provider-1"})

    return _client(handler)


def _failing() -> httpx.AsyncClient:
    """The provider is REACHABLE but rejects the send (HTTP 500)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "provider error"}})

    return _client(handler)


# Every (adapter, breaker name, credentials) triple for the newly-wired channels.
CHANNELS = [
    pytest.param(messenger_adapter, PROVIDER_MESSENGER,
                 ProviderCredentials(config={"api_key": "PAGE-TOKEN"}), id="messenger"),
    pytest.param(instagram_adapter, PROVIDER_INSTAGRAM,
                 ProviderCredentials(config={"api_key": "IG-TOKEN", "account_id": "IG-1"}),
                 id="instagram"),
    pytest.param(email_adapter, PROVIDER_EMAIL,
                 ProviderCredentials(config={"api_key": "ESP-KEY"}), id="email"),
]


# -------------------------------------------------------------- behaviour ---


@pytest.mark.parametrize(("adapter", "breaker_name", "credentials"), CHANNELS)
async def test_send_is_refused_while_the_breaker_is_open(adapter, breaker_name, credentials):
    contacted = {"n": 0}
    await _trip(breaker_name)

    with pytest.raises(CircuitOpenError):
        await adapter.send(credentials, _outbound(), _client=_counting(contacted))

    assert contacted["n"] == 0  # an OPEN breaker means the provider is not contacted


@pytest.mark.parametrize(("adapter", "breaker_name", "credentials"), CHANNELS)
async def test_a_rejecting_send_trips_the_breaker(adapter, breaker_name, credentials):
    """A provider that answers 500 to every send must open the breaker.

    This is the raise-inside-the-breaker invariant: if the status check lived
    outside ``breaker.call()`` this would record a SUCCESS and never trip.
    """
    breaker = get_breaker(breaker_name)

    for _ in range(_THRESHOLD):
        with pytest.raises(ExternalProviderError):
            await adapter.send(credentials, _outbound(), _client=_failing())

    assert breaker.is_open, "a rejecting provider must count against the breaker"


# -------------------------------------------------- registry-style guards ---


def _app_source_files() -> list[pathlib.Path]:
    return [
        p
        for p in (BACKEND_ROOT / "app").rglob("*.py")
        if "__pycache__" not in p.parts and not p.name.startswith("test_")
    ]


def _defined_breaker_names() -> list[str]:
    return [
        name
        for name, value in vars(cb).items()
        if name.startswith(("PROVIDER_", "STORAGE_")) and isinstance(value, str)
    ]


@pytest.mark.parametrize("constant", _defined_breaker_names())
def test_every_named_breaker_constant_has_a_caller(constant: str) -> None:
    """A named breaker constant with no caller is the original G-13 bug reborn.

    The registry exists so one provider has one breaker; a constant nobody passes
    to ``get_breaker`` means a real egress is going out unprotected.
    """
    defining = (BACKEND_ROOT / "app" / "core" / "circuit_breaker.py").resolve()
    callers = {
        p
        for p in _app_source_files()
        if p.resolve() != defining and _uses_name(p, constant)
    }
    assert callers, (
        f"{constant} is declared in circuit_breaker.py but never used at a call "
        f"site — the dependency it names is un-backed-off."
    )


def _uses_name(path: pathlib.Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


@pytest.mark.parametrize("path", sorted(GATEWAY_DIR.glob("*.py")))
def test_a_gateway_that_calls_out_routes_through_the_breaker(path: pathlib.Path) -> None:
    """Any gateway module that opens an ``httpx`` client must spend a breaker.

    webchat has no client and passes vacuously; a new first-party egress channel
    that opens an AsyncClient without wiring ``get_breaker`` fails here instead
    of shipping the hole this pass closed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    opens_http_client = any(
        isinstance(node, ast.Attribute) and node.attr == "AsyncClient" for node in ast.walk(tree)
    )
    if not opens_http_client:
        return
    assert _uses_name(path, "get_breaker"), (
        f"{path.name} opens an httpx client but never calls get_breaker — "
        f"external egress with no back-off."
    )
