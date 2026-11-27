"""An inbound phone call: signed, deduplicated, routed by the number that was dialled.

Telephony providers retry webhooks. The same ring can arrive three times, and a naive handler opens
three calls, three voice sessions and three bills. The provider's call id is the idempotency key: a
second delivery returns the call the first one created.

SIP headers and the caller id are untrusted input. Only the DID resolves the shop, and only after
the signature on the raw body checks out.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field, replace
from typing import Protocol

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.voice.application.session_manager import (
    VoiceSessionManager,
    VoiceSessionRecord,
)
from app.modules.voice.domain.calls import (
    CallStatus,
    LegStatus,
    LegType,
    next_call_status,
    next_leg_status,
)
from app.modules.voice.domain.recording import RecordingDecision, decide_recording
from app.modules.voice.domain.routing import DIDRouter, PersonaRoute
from app.modules.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    PrincipalType,
)


class SignatureRejected(PermissionDeniedError):
    """The body did not match the signature; nothing about this request is trustworthy."""


class SignatureVerifier:
    """HMAC-SHA256 over the raw body, compared in constant time."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValidationError("a telephony webhook needs a signing secret")
        self._secret = secret.encode()

    def check(self, *, raw_body: bytes, signature: str) -> None:
        expected = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.strip().lower()):
            raise SignatureRejected("telephony webhook signature does not match the body")


@dataclass(frozen=True, slots=True)
class CallLegRecord:
    leg_id: uuid.UUID
    leg_type: LegType
    from_number: str
    to_number: str
    status: LegStatus


@dataclass(frozen=True, slots=True)
class CallRecord:
    call_id: uuid.UUID
    tenant_id: uuid.UUID
    provider_call_id: str
    from_number: str
    to_number: str
    status: CallStatus
    legs: tuple[CallLegRecord, ...]
    recording: RecordingDecision
    persona: PersonaRoute = PersonaRoute.CUSTOMER_AGENT
    language: str = "ar-EG"
    session_id: uuid.UUID | None = None
    handoff_queue: str | None = None
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


class CallStore(Protocol):
    async def by_provider_id(self, provider_call_id: str) -> CallRecord | None: ...

    async def put(self, record: CallRecord) -> None: ...


class InMemoryCallStore:
    def __init__(self) -> None:
        self._by_provider: dict[str, CallRecord] = {}

    async def by_provider_id(self, provider_call_id: str) -> CallRecord | None:
        return self._by_provider.get(provider_call_id)

    async def put(self, record: CallRecord) -> None:
        self._by_provider[record.provider_call_id] = record


class InboundCallHandler:
    """Turns one verified webhook into one call, and never into two."""

    def __init__(
        self,
        *,
        router: DIDRouter,
        store: CallStore,
        verifier: SignatureVerifier,
        sessions: VoiceSessionManager | None = None,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._router = router
        self._store = store
        self._verifier = verifier
        self._sessions = sessions
        self._clock = clock

    async def handle(
        self, *, raw_body: bytes, signature: str, provider_call_id: str, did: str, from_number: str
    ) -> tuple[CallRecord, bool]:
        """Return the call and whether this delivery created it."""
        self._verifier.check(raw_body=raw_body, signature=signature)
        if not provider_call_id:
            raise ValidationError("a telephony webhook must carry the provider's call id")

        existing = await self._store.by_provider_id(provider_call_id)
        if existing is not None:
            return existing, False

        route = self._router.resolve(did)
        leg = CallLegRecord(
            leg_id=uuid.uuid4(),
            leg_type=LegType.INBOUND,
            from_number=from_number,
            to_number=route.did,
            status=LegStatus.RINGING,
        )
        record = CallRecord(
            call_id=uuid.uuid4(),
            tenant_id=route.tenant_id,
            provider_call_id=provider_call_id,
            from_number=from_number,
            to_number=route.did,
            status=CallStatus.RINGING,
            legs=(leg,),
            recording=decide_recording(route.recording),
            persona=route.persona,
            language=route.language,
            handoff_queue=route.handoff_queue,
            started_at=self._clock(),
        )
        await self._store.put(record)
        return record, True

    async def _require(self, provider_call_id: str) -> CallRecord:
        record = await self._store.by_provider_id(provider_call_id)
        if record is None:
            raise NotFoundError("this provider call id is not known here")
        return record

    async def answer(self, provider_call_id: str) -> CallRecord:
        """The phone was picked up: the call is in progress and a voice session may open."""
        record = await self._require(provider_call_id)
        if record.status is not CallStatus.RINGING:
            return record
        legs = tuple(
            replace(leg, status=next_leg_status(leg.status, LegStatus.ANSWERED))
            if leg.status is LegStatus.RINGING
            else leg
            for leg in record.legs
        )
        answered = replace(
            record,
            status=next_call_status(record.status, CallStatus.IN_PROGRESS),
            legs=legs,
        )
        session = await self._open_session(answered)
        if session is not None:
            answered = replace(answered, session_id=session.session_id)
        await self._store.put(answered)
        return answered

    async def _open_session(self, record: CallRecord) -> VoiceSessionRecord | None:
        if self._sessions is None:
            return None
        if record.persona is not PersonaRoute.CUSTOMER_AGENT:
            # A phone call proves a phone number, never a member of staff. The merchant persona is
            # not opened from a DID alone; that call goes to verification or to a human queue.
            return None
        return await self._sessions.start(
            principal_type=PrincipalType.CUSTOMER,
            principal_id=None,
            tenant_id=record.tenant_id,
            channel=ChannelType.PSTN,
            client_key=record.provider_call_id,
            authentication_level=AuthenticationLevel.ANONYMOUS,
        )

    async def request_handoff(self, provider_call_id: str) -> CallRecord:
        """Send the caller to staff: the session waits, the agent stops deciding."""
        record = await self._require(provider_call_id)
        if record.session_id is not None and self._sessions is not None:
            await self._sessions.begin_handoff(record.session_id, tenant_id=record.tenant_id)
        return record

    async def end(self, provider_call_id: str) -> CallRecord:
        """The call is over: every open leg closes, and an unanswered call is no_answer."""
        record = await self._require(provider_call_id)
        if record.status not in (CallStatus.RINGING, CallStatus.IN_PROGRESS):
            return record
        legs = tuple(
            replace(leg, status=next_leg_status(leg.status, LegStatus.COMPLETED))
            if leg.status in (LegStatus.RINGING, LegStatus.ANSWERED)
            else leg
            for leg in record.legs
        )
        target = (
            CallStatus.NO_ANSWER if record.status is CallStatus.RINGING else CallStatus.COMPLETED
        )
        ended = replace(record, status=next_call_status(record.status, target), legs=legs)
        await self._store.put(ended)
        return ended
