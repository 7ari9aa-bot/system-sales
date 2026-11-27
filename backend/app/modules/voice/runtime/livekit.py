"""The media plane's door: one room, one minute, and no shop name inside the credential.

The control plane decides who the caller is; this module only turns that decision into something a
browser or a phone can hand to LiveKit. Two rules are enforced here rather than documented:

* the room is the voice session id and nothing else, so a credential cannot be reused to walk into
  another shop's conversation;
* the token carries no metadata and no attributes. A tenant id or a persona inside a JWT is a
  tenant id or a persona inside a browser, and the media plane needs neither.

Signing is plain HS256 over the secret with the standard library, so issuing a credential needs no
network and can be tested without one.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from dataclasses import dataclass


class MediaPlaneUnavailable(Exception):
    """The media plane has no usable credentials, so no room can be opened."""


class MediaPlaneMisconfigured(MediaPlaneUnavailable):
    """Credentials exist but cannot be used as given."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class LiveKitCredentials:
    url: str
    api_key: str
    api_secret: str
    ttl_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.url.startswith(("wss://", "ws://")):
            raise MediaPlaneMisconfigured("livekit url must be a websocket url")
        if not self.api_key or not self.api_secret:
            raise MediaPlaneMisconfigured("livekit key and secret are both required")
        if not 1 <= self.ttl_seconds <= 300:
            raise MediaPlaneMisconfigured("token ttl must be between 1 and 300 seconds")

    @classmethod
    def from_settings(cls) -> LiveKitCredentials | None:
        """Read the project from settings. Missing values mean no media path, not a broken one."""
        from app.core.config import get_settings

        settings = get_settings()
        url = (getattr(settings, "livekit_url", "") or "").strip()
        key = (getattr(settings, "livekit_api_key", "") or "").strip()
        secret = (getattr(settings, "livekit_api_secret", "") or "").strip()
        if not url or not key or not secret:
            return None
        return cls(url=url, api_key=key, api_secret=secret)


@dataclass(frozen=True, slots=True)
class RoomGrant:
    """What one credential opens. Built by the control plane, never by the caller."""

    room: str
    identity: str
    can_publish: bool = True
    can_subscribe: bool = True
    can_publish_data: bool = False


@dataclass(frozen=True, slots=True)
class TransportCredential:
    """The answer the client needs to connect, and nothing about the shop behind it."""

    provider: str
    url: str
    token: str
    room: str
    identity: str
    expires_at: dt.datetime


class LiveKitTokenIssuer:
    """Signs one join grant at a time, for one room, with a short life."""

    def __init__(self, credentials: LiveKitCredentials) -> None:
        self._credentials = credentials

    @property
    def url(self) -> str:
        return self._credentials.url

    @property
    def ttl_seconds(self) -> int:
        return self._credentials.ttl_seconds

    def issue(self, grant: RoomGrant, *, now: dt.datetime | None = None) -> TransportCredential:
        moment = now or dt.datetime.now(dt.UTC)
        issued_at = int(moment.timestamp())
        expires_at = issued_at + self._credentials.ttl_seconds
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self._credentials.api_key,
            "sub": grant.identity,
            "nbf": issued_at - 10,
            "exp": expires_at,
            "video": {
                "room": grant.room,
                "roomJoin": True,
                "canPublish": grant.can_publish,
                "canSubscribe": grant.can_subscribe,
                "canPublishData": grant.can_publish_data,
            },
        }
        signing_input = ".".join(
            _b64(json.dumps(part, separators=(",", ":")).encode()) for part in (header, payload)
        )
        signature = hmac.new(
            self._credentials.api_secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return TransportCredential(
            provider="livekit",
            url=self._credentials.url,
            token=f"{signing_input}.{_b64(signature)}",
            room=grant.room,
            identity=grant.identity,
            expires_at=dt.datetime.fromtimestamp(expires_at, tz=dt.UTC),
        )
