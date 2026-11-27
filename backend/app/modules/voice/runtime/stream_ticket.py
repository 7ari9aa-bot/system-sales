"""A one-minute ticket that lets a browser stream audio to ONE session.

The browser cannot hold the gateway key, so the socket to GPT-Live lives on our
server and the browser streams PCM to us. That stream needs its own door, and a
door needs its own key: this ticket is signed with the app's JWT secret but
carries ``aud="voice-stream"``, so an ordinary access token can never be
presented as a stream ticket and a stream ticket can never act as an access
token. It binds the session id AND the tenant, because a ticket for another
shop's session is exactly the thing worth forging.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from dataclasses import dataclass

AUDIENCE = "voice-stream"

#: Mirrors app.core.config._INSECURE_JWT_SECRETS: a ticket signed with one of
#: these is not a credential, it is a placeholder, so issuing is refused instead.
_INSECURE_SECRETS = frozenset({"", "change-me", "changeme", "secret", "test"})


class StreamTicketUnavailable(Exception):
    """No usable signing secret, so no browser stream can be opened."""


class StreamTicketInvalid(Exception):
    """The ticket is missing, malformed, expired, or for another session."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True, slots=True)
class StreamTicketClaims:
    session_id: str
    tenant_id: str
    expires_at: int
    jti: str = ""


@dataclass(frozen=True, slots=True)
class StreamTicketIssuer:
    secret: str
    ttl_seconds: int = 60

    def __post_init__(self) -> None:
        if self.secret in _INSECURE_SECRETS:
            raise StreamTicketUnavailable("no usable signing secret for voice streaming")
        if self.ttl_seconds <= 0:
            raise StreamTicketUnavailable("a stream ticket needs a positive lifetime")

    @classmethod
    def from_settings(cls) -> StreamTicketIssuer:
        from app.core.config import get_settings

        settings = get_settings()
        return cls(secret=(getattr(settings, "jwt_secret", "") or "").strip())

    def issue(self, *, session_id, tenant_id, jti: str = "", now: dt.datetime | None = None) -> str:
        issued = now or dt.datetime.now(dt.UTC)
        expires = int(issued.timestamp()) + self.ttl_seconds
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "aud": AUDIENCE,
            "sub": str(session_id),
            "tenant": str(tenant_id),
            "nbf": int(issued.timestamp()),
            "exp": expires,
            "jti": jti,
        }
        signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}." + _b64(
            json.dumps(payload, separators=(",", ":")).encode()
        )
        signature = hmac.new(self.secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{_b64(signature)}"

    def verify(
        self, token: str, *, session_id, now: dt.datetime | None = None
    ) -> StreamTicketClaims:
        """Accept only a ticket for THIS session, and only before it expires."""
        if not token or token.count(".") != 2:
            raise StreamTicketInvalid("malformed ticket")
        signing_input, signature = token.rsplit(".", 1)
        expected = _b64(
            hmac.new(self.secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise StreamTicketInvalid("bad signature")
        try:
            header_b64, payload_b64 = signing_input.split(".")
            header = json.loads(_unb64(header_b64))
            payload = json.loads(_unb64(payload_b64))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StreamTicketInvalid("unreadable ticket") from exc
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            raise StreamTicketInvalid("unexpected algorithm")
        if not isinstance(payload, dict) or payload.get("aud") != AUDIENCE:
            raise StreamTicketInvalid("not a stream ticket")
        if str(payload.get("sub") or "") != str(session_id):
            # A ticket for another session is a ticket for another shop's call.
            raise StreamTicketInvalid("ticket is for another session")
        moment = now or dt.datetime.now(dt.UTC)
        expires = payload.get("exp")
        if not isinstance(expires, int) or expires <= int(moment.timestamp()):
            raise StreamTicketInvalid("ticket expired")
        return StreamTicketClaims(
            session_id=str(payload["sub"]),
            tenant_id=str(payload.get("tenant") or ""),
            expires_at=expires,
            jti=str(payload.get("jti") or ""),
        )
