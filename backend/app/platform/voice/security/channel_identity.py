"""Linking a channel handle to a customer, and refusing to guess the link.

A WhatsApp number, an Instagram handle or a Messenger PSID identifies a conversation, not a person
with a right to see orders. The link to a customer exists only when something proved it: a verified
code on that channel, or a signed-in account that connected the handle. Until then the handle is a
clue, exactly like a Caller ID, and the session stays at the anonymous level.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.platform.voice.security.capabilities import AuthenticationLevel, ChannelType


@dataclass(frozen=True, slots=True)
class ChannelHandle:
    channel: ChannelType
    external_id: str
    tenant_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class HandleLink:
    handle: ChannelHandle
    customer_id: uuid.UUID
    level: AuthenticationLevel
    proved_at: dt.datetime
    expires_at: dt.datetime | None = None
    method: str = "otp"

    def is_valid(self, now: dt.datetime) -> bool:
        return self.expires_at is None or now < self.expires_at


class LinkStore(Protocol):
    async def find(self, handle: ChannelHandle) -> HandleLink | None: ...

    async def put(self, link: HandleLink) -> None: ...


class InMemoryLinkStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[ChannelType, str, uuid.UUID], HandleLink] = {}

    async def find(self, handle: ChannelHandle) -> HandleLink | None:
        return self._rows.get((handle.channel, handle.external_id, handle.tenant_id))

    async def put(self, link: HandleLink) -> None:
        key = (link.handle.channel, link.handle.external_id, link.handle.tenant_id)
        self._rows[key] = link


@dataclass(frozen=True, slots=True)
class HandleResolution:
    """What a handle is allowed to mean right now, and why."""

    handle: ChannelHandle
    customer_id: uuid.UUID | None
    level: AuthenticationLevel
    reason: str


class ChannelIdentityResolver:
    """Turns a handle into an identity only through a valid, proved link."""

    def __init__(self, store: LinkStore, *, clock=lambda: dt.datetime.now(dt.UTC)) -> None:
        self._store = store
        self._clock = clock

    async def resolve(self, handle: ChannelHandle) -> HandleResolution:
        link = await self._store.find(handle)
        if link is None:
            return HandleResolution(
                handle=handle,
                customer_id=None,
                level=AuthenticationLevel.ANONYMOUS,
                reason="no proved link between this handle and a customer",
            )
        if not link.is_valid(self._clock()):
            return HandleResolution(
                handle=handle,
                customer_id=None,
                level=AuthenticationLevel.IDENTIFIED,
                reason="the link existed but has expired; verify again",
            )
        return HandleResolution(
            handle=handle,
            customer_id=link.customer_id,
            level=link.level,
            reason=f"linked via {link.method}",
        )
