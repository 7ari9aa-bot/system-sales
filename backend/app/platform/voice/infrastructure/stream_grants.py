"""What a stream ticket stands for, kept on the server for one minute.

A ticket is a signed reference, not a bag of permissions: putting a shop's
permission codes inside a token that travels to a browser would hand the client a
readable list of what it may do. Instead the HTTP request that mints the ticket
resolves the caller once (through the SAME ``build_tenant_context`` the rest of
the API uses) and leaves the identity here, keyed by a random id that the ticket
carries. The websocket then redeems it exactly once.

Single use matters: a ticket that leaked can open nothing after the browser it was
minted for has connected, and the grant dies with the call either way.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 60
KEY_PREFIX = "voice:stream:"


class StreamGrantMissing(Exception):
    """The grant was never issued, already redeemed, or has expired."""


@dataclass(frozen=True, slots=True)
class StreamGrant:
    session_id: str
    tenant_id: str
    user_id: str


class StreamGrantStore:
    """A one-minute, single-use identity store backed by Redis."""

    def __init__(self, client, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl = ttl_seconds

    @classmethod
    def from_settings(cls) -> StreamGrantStore:
        from app.core.redis import get_redis

        return cls(get_redis())

    async def grant(self, *, session_id, tenant_id, user_id) -> str:
        jti = secrets.token_urlsafe(18)
        payload = json.dumps(
            {
                "session_id": str(session_id),
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
            }
        )
        await self._client.setex(f"{KEY_PREFIX}{jti}", self._ttl, payload)
        return jti

    async def take(self, jti: str) -> StreamGrant:
        """Redeem the grant. A second redemption finds nothing, by design."""
        key = f"{KEY_PREFIX}{jti}"
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        value, _ = await pipe.execute()
        if not value:
            raise StreamGrantMissing("no live grant for this ticket")
        raw = value.decode() if isinstance(value, bytes) else value
        data = json.loads(raw)
        return StreamGrant(
            session_id=str(data["session_id"]),
            tenant_id=str(data["tenant_id"]),
            user_id=str(data["user_id"]),
        )
