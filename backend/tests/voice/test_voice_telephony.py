"""Phase 4: a signed webhook, one call per ring, and a DID that decides the shop."""

from __future__ import annotations

import hashlib
import hmac
import uuid

import pytest

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.voice.application.inbound_calls import (
    InboundCallHandler,
    InMemoryCallStore,
    SignatureRejected,
    SignatureVerifier,
)
from app.modules.voice.application.session_manager import (
    InMemorySessionStore,
    VoiceSessionManager,
)
from app.modules.voice.domain.calls import (
    CallStatus,
    IllegalCallTransition,
    LegStatus,
    next_call_status,
)
from app.modules.voice.domain.recording import decide_recording
from app.modules.voice.domain.routing import (
    BusinessHours,
    DIDRouter,
    PersonaRoute,
    PhoneRoute,
    RecordingMode,
    RouteType,
)
from app.modules.voice.domain.states import VoiceSessionState

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
SECRET = "provider-signing-secret"
DID = "+201000000001"


def _route(**kwargs) -> PhoneRoute:
    base = dict(
        did=DID,
        tenant_id=TENANT,
        workspace_id=None,
        route_type=RouteType.CUSTOMER_PUBLIC,
        persona=PersonaRoute.CUSTOMER_AGENT,
        hours=BusinessHours(timezone="Africa/Cairo", open_hour=0, close_hour=24),
    )
    base.update(kwargs)
    return PhoneRoute(**base)


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _handler(route: PhoneRoute | None = None, *, sessions: bool = True) -> InboundCallHandler:
    router = DIDRouter({DID: route or _route()})
    manager = VoiceSessionManager(InMemorySessionStore()) if sessions else None
    return InboundCallHandler(
        router=router,
        store=InMemoryCallStore(),
        verifier=SignatureVerifier(SECRET),
        sessions=manager,
    )


class TestInboundCall:
    async def test_a_retried_webhook_returns_the_same_call(self) -> None:
        handler = _handler()
        body = b'{"event":"call.incoming"}'
        first, created_first = await handler.handle(
            raw_body=body,
            signature=_sign(body),
            provider_call_id="pc-1",
            did=DID,
            from_number="+201111111111",
        )
        second, created_second = await handler.handle(
            raw_body=body,
            signature=_sign(body),
            provider_call_id="pc-1",
            did=DID,
            from_number="+201111111111",
        )
        assert created_first is True
        assert created_second is False
        assert second.call_id == first.call_id
        assert len(first.legs) == 1

    async def test_a_body_that_does_not_match_its_signature_is_refused(self) -> None:
        handler = _handler()
        with pytest.raises(SignatureRejected):
            await handler.handle(
                raw_body=b'{"event":"call.incoming"}',
                signature="0" * 64,
                provider_call_id="pc-2",
                did=DID,
                from_number="+201111111111",
            )

    async def test_an_unknown_number_is_not_routed_to_any_shop(self) -> None:
        handler = _handler()
        body = b"{}"
        with pytest.raises(NotFoundError):
            await handler.handle(
                raw_body=body,
                signature=_sign(body),
                provider_call_id="pc-3",
                did="+201999999999",
                from_number="+201111111111",
            )

    async def test_answering_opens_one_customer_session_and_ending_closes_the_call(self) -> None:
        handler = _handler()
        body = b"{}"
        call, _ = await handler.handle(
            raw_body=body,
            signature=_sign(body),
            provider_call_id="pc-4",
            did=DID,
            from_number="+201111111111",
        )
        answered = await handler.answer("pc-4")
        assert answered.status is CallStatus.IN_PROGRESS
        assert answered.legs[0].status is LegStatus.ANSWERED
        assert answered.session_id is not None

        again = await handler.answer("pc-4")
        assert again.session_id == answered.session_id

        ended = await handler.end("pc-4")
        assert ended.status is CallStatus.COMPLETED
        assert ended.legs[0].status is LegStatus.COMPLETED


class TestMerchantNumberAndRecording:
    async def test_a_merchant_private_number_never_opens_the_merchant_persona(self) -> None:
        handler = _handler(
            _route(route_type=RouteType.MERCHANT_PRIVATE, persona=PersonaRoute.MERCHANT_ASSISTANT)
        )
        body = b"{}"
        await handler.handle(
            raw_body=body,
            signature=_sign(body),
            provider_call_id="pc-5",
            did=DID,
            from_number="+201111111111",
        )
        answered = await handler.answer("pc-5")
        assert answered.persona is PersonaRoute.MERCHANT_ASSISTANT
        assert answered.session_id is None

    async def test_handoff_moves_the_session_and_keeps_the_call_up(self) -> None:
        handler = _handler(_route(handoff_queue="support-1"))
        body = b"{}"
        await handler.handle(
            raw_body=body,
            signature=_sign(body),
            provider_call_id="pc-6",
            did=DID,
            from_number="+201111111111",
        )
        answered = await handler.answer("pc-6")
        await handler.request_handoff("pc-6")
        session = await handler._sessions.require(answered.session_id)  # type: ignore[union-attr]
        assert session.state is VoiceSessionState.HANDOFF_PENDING
        assert answered.handoff_queue == "support-1"

    def test_recording_is_off_unless_the_number_asks_for_it(self) -> None:
        assert decide_recording(None).allowed is False
        assert decide_recording(RecordingMode.OFF).allowed is False
        notice = decide_recording(RecordingMode.WITH_NOTICE)
        assert notice.allowed is True and notice.notice_required is True
        consent = decide_recording(RecordingMode.WITH_CONSENT)
        assert consent.allowed is False and consent.consent_required is True
        consented = decide_recording(RecordingMode.WITH_CONSENT, consent_captured=True)
        assert consented.allowed is True

    def test_a_call_cannot_go_back_to_ringing(self) -> None:
        with pytest.raises(IllegalCallTransition):
            next_call_status(CallStatus.IN_PROGRESS, CallStatus.RINGING)

    def test_an_inactive_number_refuses_calls(self) -> None:
        router = DIDRouter({DID: _route(active=False)})
        with pytest.raises(PermissionDeniedError):
            router.resolve(DID)
