"""The voice path spends model budget, so it carries the text path's plan gate.

``require_ai_entitlement`` (capability ``CanUseAI``) is what refuses a tenant whose plan does not
sell the AI agents on the typed assistant — ``AnalyticsAICtx`` in
``app/applications/apparel/modules/ai/routers/_deps.py``. The voice control plane used to check only ``analytics:read``,
so the same tenant could open a paid realtime session and stream audio to the model.

These cases pin three things, without a database (the harness is the same as the rest of
``tests/voice``: the routes are called directly and the gates they DECLARE are read off the
router's dependency tree, so a check that later moves into an endpoint body cannot slip past):

* the routes that mint a session, a media-plane credential or a stream ticket declare the plan
  gate on top of the existing capability and identity checks;
* the control routes (read, interrupt, handoff, close) do not — a shop that downgrades mid-call
  must still be able to end the call it already started;
* the refusal is the text path's, unchanged: 403, ``permission_denied``, the same body.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Annotated, get_args, get_origin

import pytest

from app.core.ai_entitlement import require_ai_entitlement
from app.core.errors import PermissionDeniedError
from app.applications.apparel.modules.ai.chat import service as chat_service
from app.applications.apparel.modules.ai.routers import _deps as ai_deps
from app.modules.voice.application.session_manager import (
    InMemorySessionStore,
    VoiceSessionManager,
)
from app.modules.voice.routers import sessions as api

TENANT = uuid.uuid4()
USER = uuid.uuid4()
SESSION = uuid.uuid4()

#: The routes that MINT something: a session, the media-plane credential, the stream ticket.
MINTING = (
    ("POST", "/voice/sessions"),
    ("POST", "/voice/sessions/{session_id}/transport"),
    ("POST", "/voice/sessions/{session_id}/stream-ticket"),
)
#: The routes that only control a call that already exists.
CONTROL = (
    ("GET", "/voice/sessions/{session_id}"),
    ("POST", "/voice/sessions/{session_id}/interrupt"),
    ("POST", "/voice/sessions/{session_id}/handoff"),
    ("POST", "/voice/sessions/{session_id}/close"),
)


def _route(path: str, method: str):
    for route in api.router.routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route
    raise AssertionError(f"{method} {path} is not routed")


def _declared_calls(path: str, method: str) -> list[object]:
    """Every dependency callable a route declares, found by walking its tree."""
    calls: list[object] = []
    stack = list(_route(path, method).dependant.dependencies)
    while stack:
        dependant = stack.pop()
        calls.append(dependant.call)
        stack.extend(dependant.dependencies)
    return calls


def _declared_codes(path: str, method: str) -> set[str]:
    return {call.code for call in _declared_calls(path, method) if getattr(call, "code", None)}


def _gate_instances(alias: object) -> list[object]:
    """The dependency instances an ``Annotated[..., Depends(...)]`` alias declares."""
    return [meta.dependency for meta in get_args(alias)[1:] if hasattr(meta, "dependency")]


class _SessionRow:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.ai_chat_thread_id = None


class _DbStub:
    """Just enough AsyncSession for the thread bridge; nothing here reads a database."""

    async def execute(self, _statement: object) -> object:
        row = _SessionRow()
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    async def flush(self) -> None:
        return None


def _ctx(permissions: set[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        session=_DbStub(),
        user=SimpleNamespace(id=USER),
        tenant_id=TENANT,
        workspace_id=None,
        permission_codes=permissions or {"analytics:read", "orders:read", "inventory:read"},
    )


@pytest.fixture()
def manager(monkeypatch: pytest.MonkeyPatch) -> VoiceSessionManager:
    built = VoiceSessionManager(InMemorySessionStore())
    monkeypatch.setattr(api, "_manager", lambda _ctx: built)

    async def _fake_create_thread(_session, _ctx, *, title=None, context=None):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(chat_service, "create_thread", _fake_create_thread)
    return built


def _entitlement(monkeypatch: pytest.MonkeyPatch, *, allowed: bool) -> None:
    async def _can(session, tenant_id, capability):
        assert capability == "CanUseAI"
        return allowed

    monkeypatch.setattr(
        "app.modules.billing.services.entitlements.EntitlementService.can",
        _can,
    )


class TestTheRoutesDeclareTheGate:
    @pytest.mark.parametrize(("method", "path"), MINTING)
    def test_a_minting_route_carries_the_plan_gate_and_the_capability(
        self, method: str, path: str
    ) -> None:
        codes = _declared_codes(path, method)

        assert "analytics:read" in codes  # the capability check is unchanged
        assert "CanUseAI" in codes  # ... and the plan gate the text route carries

    @pytest.mark.parametrize(("method", "path"), CONTROL)
    def test_a_control_route_keeps_its_capability_without_the_plan_gate(
        self, method: str, path: str
    ) -> None:
        codes = _declared_codes(path, method)

        assert "analytics:read" in codes
        assert "CanUseAI" not in codes

    @pytest.mark.parametrize(("method", "path"), MINTING)
    def test_the_voice_routes_use_the_text_path_s_own_gate_object(
        self, method: str, path: str
    ) -> None:
        """One class, so the two paths cannot drift into different refusals."""
        assert ai_deps.require_ai_entitlement is require_ai_entitlement
        assert any(
            isinstance(gate, require_ai_entitlement)
            for gate in _gate_instances(ai_deps.AnalyticsAICtx)
        )

        assert any(
            isinstance(call, require_ai_entitlement) for call in _declared_calls(path, method)
        )

    def test_the_voice_alias_is_one_dependency_that_composes_both_checks(self) -> None:
        """Two stacked ``Depends`` would lose the permission: FastAPI keeps only the last.

        So the voice gate is a single callable whose own signature declares ``analytics:read`` and
        ``CanUseAI`` as sub-dependencies — which is what the tree walk above proves. Here we pin
        that the alias itself is annotated, i.e. FastAPI actually runs it.
        """
        assert get_origin(api.VoiceAICtx) is Annotated
        gates = _gate_instances(api.VoiceAICtx)

        assert [type(gate) for gate in gates] == [api.require_voice_ai]
        assert gates[0].code == "CanUseAI"


class TestTheRefusal:
    async def test_an_entitled_tenant_opens_a_session(
        self, monkeypatch: pytest.MonkeyPatch, manager: VoiceSessionManager
    ) -> None:
        _entitlement(monkeypatch, allowed=True)
        ctx = _ctx()

        await require_ai_entitlement()(ctx)  # what the route's dependency does first
        response = await api.start_session(ctx, api.StartSessionRequest())

        assert response.persona == "merchant_assistant"
        assert response.tenant_id == TENANT
        assert "analytics:read" in response.scopes

    async def test_an_unentitled_tenant_is_refused_with_the_text_path_s_refusal(
        self, monkeypatch: pytest.MonkeyPatch, manager: VoiceSessionManager
    ) -> None:
        _entitlement(monkeypatch, allowed=False)

        with pytest.raises(PermissionDeniedError) as refused:
            await require_ai_entitlement()(_ctx())

        # The text path's exact refusal: 403, permission_denied, same message, same body.
        assert refused.value.http_status == 403
        assert refused.value.code == "permission_denied"
        assert refused.value.message == "plan does not allow AI agents"
        assert refused.value.details == {"capability": "CanUseAI"}

    async def test_an_unentitled_tenant_cannot_reach_the_audio_stream(self) -> None:
        """The socket's only credential is the ticket, and minting one is gated."""
        assert "CanUseAI" in _declared_codes("/voice/sessions/{session_id}/stream-ticket", "POST")

        socket = _WebSocket()
        await api.stream_audio(socket, SESSION, ticket="")

        assert socket.closed_with == 1008


class _WebSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code
