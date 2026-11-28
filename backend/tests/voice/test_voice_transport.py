"""The media credential: one room, one minute, and no shop name carried into the browser.

The token is checked by decoding it with the same secret LiveKit will use, so these tests prove the
credential rather than the shape of a function call. No network is involved anywhere.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ConflictError, NotFoundError, StorageUnavailableError
from app.platform.voice.application.session_manager import (
    InMemorySessionStore,
    VoiceSessionManager,
)
from app.platform.voice.application.transport import VoiceTransportService
from app.platform.voice.domain.personas import PrincipalType
from app.platform.voice.routers import sessions as api
from app.platform.voice.runtime.livekit import (
    LiveKitCredentials,
    LiveKitTokenIssuer,
    MediaPlaneMisconfigured,
    MediaPlaneUnavailable,
)
from app.platform.voice.security.capabilities import ChannelType

TENANT = uuid.uuid4()
USER = uuid.uuid4()
CREDENTIALS = LiveKitCredentials(
    url="wss://voice-agent-test.livekit.cloud",
    api_key="APItestkey",
    api_secret="secret-that-is-long-enough-to-sign",
)


def _ctx(tenant_id: uuid.UUID = TENANT) -> SimpleNamespace:
    return SimpleNamespace(
        session=None,
        user=SimpleNamespace(id=USER),
        tenant_id=tenant_id,
        workspace_id=None,
        permission_codes={"orders:read", "inventory:read"},
    )


def _decode(token: str) -> dict:
    head, body, _ = token.split(".")
    padded = body + "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _signature(token: str, secret: str) -> str:
    head, body, _ = token.split(".")
    return (
        base64.urlsafe_b64encode(
            hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode()
    )


@pytest.fixture()
def manager(monkeypatch: pytest.MonkeyPatch) -> VoiceSessionManager:
    built = VoiceSessionManager(InMemorySessionStore())
    monkeypatch.setattr(api, "_manager", lambda _ctx: built)
    return built


@pytest.fixture()
def transport(monkeypatch: pytest.MonkeyPatch) -> VoiceTransportService:
    built = VoiceTransportService(lambda: LiveKitTokenIssuer(CREDENTIALS))
    monkeypatch.setattr(api, "_transport", lambda: built)
    return built


async def _open(manager: VoiceSessionManager, channel: ChannelType = ChannelType.WEB_VOICE):
    return await manager.start(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=USER,
        tenant_id=TENANT,
        workspace_id=None,
        held_scopes=frozenset({"orders:read"}),
        channel=channel,
    )


class TestTheCredentialItself:
    async def test_it_expires_in_about_a_minute(self, transport: VoiceTransportService) -> None:
        record = await _open(VoiceSessionManager(InMemorySessionStore()))
        credential = transport.issue_for(record)
        payload = _decode(credential.token)
        assert 50 <= payload["exp"] - int(time.time()) <= 61

    async def test_it_opens_the_session_room_and_nothing_else(
        self, transport: VoiceTransportService
    ) -> None:
        record = await _open(VoiceSessionManager(InMemorySessionStore()))
        credential = transport.issue_for(record)
        payload = _decode(credential.token)
        assert payload["video"]["room"] == str(record.session_id)
        assert payload["video"]["roomJoin"] is True
        assert credential.room == str(record.session_id)

    async def test_no_tenant_and_no_persona_travel_in_the_token(
        self, transport: VoiceTransportService
    ) -> None:
        record = await _open(VoiceSessionManager(InMemorySessionStore()))
        credential = transport.issue_for(record)
        payload = _decode(credential.token)
        # A fixed claim set: anything extra would be an identity leak by accident later.
        assert set(payload) == {"iss", "sub", "nbf", "exp", "video"}
        raw = json.dumps(payload)
        assert str(TENANT) not in raw
        assert record.persona.value not in raw
        assert "tenant" not in raw

    async def test_a_token_signed_with_another_secret_does_not_verify(
        self, transport: VoiceTransportService
    ) -> None:
        record = await _open(VoiceSessionManager(InMemorySessionStore()))
        token = transport.issue_for(record).token
        head, _, signature = token.split(".")
        assert _signature(token, CREDENTIALS.api_secret) == signature
        assert _signature(token, "a-different-secret") != signature
        assert head  # the header is present and decodable
        assert _decode(token)["iss"] == CREDENTIALS.api_key

    def test_a_url_that_is_not_a_websocket_is_refused(self) -> None:
        with pytest.raises(MediaPlaneMisconfigured):
            LiveKitCredentials(url="https://example.com", api_key="k", api_secret="s")


class TestWhenTheRoomIsRefused:
    async def test_a_voice_note_channel_gets_no_room(
        self, transport: VoiceTransportService
    ) -> None:
        record = await _open(
            VoiceSessionManager(InMemorySessionStore()), ChannelType.WHATSAPP_VOICE
        )
        with pytest.raises(ConflictError) as refused:
            transport.issue_for(record)
        assert "file" in str(refused.value)

    async def test_a_failed_session_gets_no_room(self, transport: VoiceTransportService) -> None:
        manager = VoiceSessionManager(InMemorySessionStore())
        record = await _open(manager)
        failed = await manager.fail(record.session_id, reason="provider dropped before audio")
        with pytest.raises(ConflictError):
            transport.issue_for(failed)

    def test_an_unconfigured_media_plane_says_so(self) -> None:
        def build() -> LiveKitTokenIssuer:
            raise MediaPlaneUnavailable("no credentials")

        record = SimpleNamespace(
            session_id=uuid.uuid4(),
            state=None,
            capability=SimpleNamespace(channel=ChannelType.WEB_VOICE),
        )
        from app.platform.voice.domain.states import VoiceSessionState

        record.state = VoiceSessionState.CONFIGURING
        with pytest.raises(MediaPlaneUnavailable):
            VoiceTransportService(build).issue_for(record)  # type: ignore[arg-type]


class TestTheEndpoint:
    async def test_it_returns_a_credential_for_the_room_the_caller_opened(
        self, manager: VoiceSessionManager, transport: VoiceTransportService
    ) -> None:
        record = await _open(manager)
        answer = await api.open_transport(_ctx(), record.session_id)
        assert answer.room == str(record.session_id)
        assert answer.provider == "livekit"
        assert answer.url == CREDENTIALS.url
        assert _decode(answer.token)["video"]["room"] == str(record.session_id)

    async def test_a_session_from_another_shop_is_not_found(
        self, manager: VoiceSessionManager, transport: VoiceTransportService
    ) -> None:
        record = await _open(manager)
        with pytest.raises(NotFoundError):
            await api.open_transport(_ctx(tenant_id=uuid.uuid4()), record.session_id)

    async def test_a_control_plane_without_a_media_plane_answers_unavailable(
        self, manager: VoiceSessionManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def build() -> VoiceTransportService:
            raise MediaPlaneUnavailable("not configured")

        monkeypatch.setattr(api, "_transport", build)
        record = await _open(manager)
        with pytest.raises(StorageUnavailableError):
            await api.open_transport(_ctx(), record.session_id)
