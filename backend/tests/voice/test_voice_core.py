"""Phase 1: a session that keeps its identity, its tenant and its permissions through a turn.

These run without a database and without a provider: the store is in memory and the provider is a
fake that can be told to drop. What is proven here is the behaviour the architecture promises —
the happy path, the refusal paths, and recovery after the media path dies.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.voice.application.session_manager import (
    InMemorySessionStore,
    VoiceSessionManager,
)
from app.modules.voice.application.turn_orchestrator import ToolCall, TurnOrchestrator
from app.modules.voice.domain.contracts import AudioPath, ProviderCapabilities
from app.modules.voice.domain.personas import PrincipalType
from app.modules.voice.domain.states import TurnState, VoiceSessionState
from app.modules.voice.runtime.providers import (
    FakeRealtimeProvider,
    NoProviderAvailable,
    ProviderRouter,
)
from app.modules.voice.runtime.recovery import SessionRecovery
from app.modules.voice.security.capabilities import AuthenticationLevel, ToolGateway

TENANT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _manager(store=None) -> VoiceSessionManager:
    return VoiceSessionManager(store or InMemorySessionStore())


async def _merchant_session(manager=None, scopes=("orders:read", "inventory:read")):
    manager = manager or _manager()
    return manager, await manager.start(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=USER,
        tenant_id=TENANT,
        held_scopes=frozenset(scopes),
    )


class TestSessionLifecycle:
    async def test_a_started_session_holds_the_persona_and_a_trace(self) -> None:
        _, record = await _merchant_session()
        assert record.state is VoiceSessionState.CONFIGURING
        assert record.persona.value == "merchant_assistant"
        assert record.capability.scopes == frozenset({"orders:read", "inventory:read"})
        assert record.trace_id.startswith("voice-")
        assert record.tenant_id == TENANT

    async def test_the_same_client_key_does_not_open_a_second_session(self) -> None:
        manager, first = await _merchant_session()
        second = await manager.start(
            principal_type=PrincipalType.MERCHANT_USER,
            principal_id=USER,
            tenant_id=TENANT,
            held_scopes=frozenset({"orders:read"}),
            client_key="phone-retry-1",
        )
        again = await manager.start(
            principal_type=PrincipalType.MERCHANT_USER,
            principal_id=USER,
            tenant_id=TENANT,
            held_scopes=frozenset({"orders:read"}),
            client_key="phone-retry-1",
        )
        assert second.session_id == again.session_id
        assert second.session_id != first.session_id

    async def test_a_session_reached_with_another_tenant_is_refused(self) -> None:
        manager, record = await _merchant_session()
        await manager.for_tenant(record.session_id, TENANT)
        with pytest.raises(PermissionDeniedError):
            await manager.for_tenant(record.session_id, OTHER_TENANT)

    async def test_an_unknown_session_is_not_found(self) -> None:
        manager = _manager()
        with pytest.raises(NotFoundError):
            await manager.require(uuid.uuid4())

    async def test_a_closed_session_cannot_be_moved_again(self) -> None:
        manager, record = await _merchant_session()
        await manager.attach_provider(record.session_id, "fake-1")
        await manager.activate(record.session_id)
        await manager.close(record.session_id)
        with pytest.raises(ConflictError):
            await manager.activate(record.session_id)

    async def test_a_customer_starts_with_public_scopes_only(self) -> None:
        manager = _manager()
        record = await manager.start(
            principal_type=PrincipalType.CUSTOMER,
            principal_id=None,
            tenant_id=TENANT,
        )
        assert "catalog.published:read" in record.capability.scopes
        assert "customer.own_orders:read" not in record.capability.scopes

    async def test_a_verified_customer_earns_their_own_orders(self) -> None:
        manager = _manager()
        record = await manager.start(
            principal_type=PrincipalType.CUSTOMER,
            principal_id=uuid.uuid4(),
            tenant_id=TENANT,
            authentication_level=AuthenticationLevel.VERIFIED,
        )
        assert "customer.own_orders:read" in record.capability.scopes
        assert "analytics:read" not in record.capability.scopes


class TestTurnOrchestration:
    async def _active(self, scopes=("orders:read",)):
        manager, record = await _merchant_session(scopes=scopes)
        await manager.attach_provider(record.session_id, "fake-1")
        record = await manager.activate(record.session_id)
        return manager, record

    async def test_a_turn_reads_through_the_gateway_and_speaks_the_answer(self) -> None:
        _, record = await self._active()
        seen: list[str] = []

        async def runner(call: ToolCall) -> dict:
            seen.append(call.name)
            return {"orders": 3}

        turn = TurnOrchestrator(ToolGateway(), runner).begin(1, "كام طلب النهاردة؟")
        orchestrator = TurnOrchestrator(ToolGateway(), runner)
        result = await orchestrator.call_tool(turn, record.capability, ToolCall("orders.read"))
        orchestrator.speak(turn, "عندك 3 طلبات النهاردة.")

        assert result == {"orders": 3}
        assert seen == ["orders.read"]
        assert turn.state is TurnState.COMPLETED
        assert turn.spoken == "عندك 3 طلبات النهاردة."

    async def test_a_tool_outside_the_session_scopes_is_refused(self) -> None:
        _, record = await self._active(scopes=("orders:read",))

        async def runner(call: ToolCall) -> dict:  # pragma: no cover - never reached
            raise AssertionError("the gateway must refuse before the runner runs")

        orchestrator = TurnOrchestrator(ToolGateway(), runner)
        turn = orchestrator.begin(1, "إيه المصاريف؟")
        with pytest.raises(PermissionDeniedError):
            await orchestrator.call_tool(turn, record.capability, ToolCall("expenses.read"))

    async def test_the_merchant_assistant_can_never_write(self) -> None:
        _, record = await self._active(scopes=("orders:read",))

        async def runner(call: ToolCall) -> dict:  # pragma: no cover - never reached
            raise AssertionError("a write tool must never reach the runner")

        orchestrator = TurnOrchestrator(ToolGateway(), runner)
        turn = orchestrator.begin(1, "الغي الطلب")
        with pytest.raises(PermissionDeniedError):
            await orchestrator.call_tool(turn, record.capability, ToolCall("orders.create"))

    async def test_an_interrupted_turn_neither_calls_nor_speaks(self) -> None:
        _, record = await self._active()
        ran: list[str] = []

        async def runner(call: ToolCall) -> dict:
            ran.append(call.name)
            return {}

        orchestrator = TurnOrchestrator(ToolGateway(), runner)
        turn = orchestrator.begin(1, "وريني العشر منتجات")
        orchestrator.interrupt(turn)
        await orchestrator.call_tool(turn, record.capability, ToolCall("orders.read"))
        orchestrator.speak(turn, "أول منتج…")

        assert ran == []
        assert turn.spoken is None
        assert turn.dropped_results == ["orders.read", "speech"]
        assert turn.state is TurnState.INTERRUPTED


class TestProviderRouting:
    def _router(self, provider: FakeRealtimeProvider) -> ProviderRouter:
        router = ProviderRouter()
        router.register(
            "openai-live",
            ProviderCapabilities(
                name="openai-live",
                paths=frozenset({AudioPath.SPEECH_TO_SPEECH}),
                languages=frozenset({"ar", "en"}),
                supports_barge_in=True,
            ),
            provider,
        )
        router.register(
            "cascaded",
            ProviderCapabilities(
                name="cascaded",
                paths=frozenset({AudioPath.CASCADED}),
                languages=frozenset({"ar-EG", "ar-SA", "en"}),
            ),
            provider,
        )
        return router

    def test_the_router_serves_only_what_a_provider_declared(self) -> None:
        router = self._router(FakeRealtimeProvider())
        assert router.choose(path=AudioPath.CASCADED, language="ar-EG").name == "cascaded"
        assert router.choose(path=AudioPath.SPEECH_TO_SPEECH, language="ar-EG").name == (
            "openai-live"
        )

    def test_an_undeclared_language_has_no_provider(self) -> None:
        router = self._router(FakeRealtimeProvider())
        with pytest.raises(NoProviderAvailable):
            router.choose(path=AudioPath.SPEECH_TO_SPEECH, language="fr")

    def test_an_unavailable_provider_is_skipped(self) -> None:
        router = self._router(FakeRealtimeProvider())
        router.register(
            "gemini-live",
            ProviderCapabilities(
                name="gemini-live",
                paths=frozenset({AudioPath.SPEECH_TO_SPEECH}),
                languages=frozenset({"ar"}),
                supports_barge_in=True,
            ),
            FakeRealtimeProvider(),
        )
        entry = router.choose(
            path=AudioPath.SPEECH_TO_SPEECH,
            language="ar",
            prefer="openai-live",
            unavailable=frozenset({"openai-live"}),
        )
        assert entry.name == "gemini-live"

    def test_when_every_provider_for_the_path_is_down_it_refuses(self) -> None:
        router = self._router(FakeRealtimeProvider())
        with pytest.raises(NoProviderAvailable):
            router.choose(
                path=AudioPath.SPEECH_TO_SPEECH,
                language="ar",
                unavailable=frozenset({"openai-live"}),
            )


class TestRecovery:
    async def test_a_dropped_session_resumes_the_same_identity_and_last_turn(self) -> None:
        manager, record = await _merchant_session()
        provider = FakeRealtimeProvider()
        router = ProviderRouter()
        router.register(
            "openai-live",
            ProviderCapabilities(
                name="openai-live",
                paths=frozenset({AudioPath.SPEECH_TO_SPEECH}),
                languages=frozenset({"ar"}),
                supports_barge_in=True,
            ),
            provider,
        )
        await manager.attach_provider(record.session_id, await provider.create_session({}))
        await manager.activate(record.session_id)
        await manager.note_turn_completed(record.session_id, 4)

        # The primary drops; a second provider that declared the same path takes over.
        provider.up = False
        standby = FakeRealtimeProvider()
        router.register(
            "gemini-live",
            ProviderCapabilities(
                name="gemini-live",
                paths=frozenset({AudioPath.SPEECH_TO_SPEECH}),
                languages=frozenset({"ar"}),
                supports_barge_in=True,
            ),
            standby,
        )
        plan = await SessionRecovery(manager, router).recover(
            record.session_id,
            path=AudioPath.SPEECH_TO_SPEECH,
            language="ar-EG",
            unavailable=frozenset({"openai-live"}),
        )

        recovered = await manager.require(record.session_id)
        assert plan.session_id == str(record.session_id)
        assert plan.resume_from_turn == 4
        assert recovered.tenant_id == TENANT
        assert recovered.capability.scopes == record.capability.scopes
        assert recovered.state is VoiceSessionState.ACTIVE
        assert recovered.provider_session_id != record.provider_session_id

    async def test_recovery_with_no_provider_available_fails_loudly(self) -> None:
        manager, record = await _merchant_session()
        await manager.attach_provider(record.session_id, "fake-1")
        await manager.activate(record.session_id)
        with pytest.raises(NoProviderAvailable):
            await SessionRecovery(manager, ProviderRouter()).recover(
                record.session_id, path=AudioPath.SPEECH_TO_SPEECH, language="ar"
            )
