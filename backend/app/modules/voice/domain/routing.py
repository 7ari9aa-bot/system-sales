"""Which shop answers this number, as which persona, and what happens when nobody can.

The number the customer dialled decides the tenant. A number the caller *says* they dialled, or the
number they are calling *from*, decides nothing: a caller id is a hint, and a spoken number is
untrusted data.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.errors import NotFoundError, PermissionDeniedError


class RouteType(enum.StrEnum):
    """What a DID is for. A shop may hold several; they never substitute for each other."""

    CUSTOMER_PUBLIC = "customer_public"
    MERCHANT_PRIVATE = "merchant_private"
    HUMAN_SUPPORT = "human_support"
    EXTERNAL_FORWARD = "external_forward"


class PersonaRoute(enum.StrEnum):
    CUSTOMER_AGENT = "customer_agent"
    MERCHANT_ASSISTANT = "merchant_assistant"
    HUMAN_QUEUE = "human_queue"
    FORWARD_ONLY = "forward_only"


class RecordingMode(enum.StrEnum):
    OFF = "off"
    WITH_NOTICE = "with_notice"
    WITH_CONSENT = "with_consent"


@dataclass(frozen=True, slots=True)
class BusinessHours:
    """Open hours in the shop's own timezone; a call outside them is not an emergency."""

    timezone: str
    open_hour: int = 9
    close_hour: int = 21
    weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5, 6})

    def is_open(self, moment: dt.datetime) -> bool:
        local = moment.astimezone(dt.timezone(dt.timedelta(0)))
        try:
            from zoneinfo import ZoneInfo

            local = moment.astimezone(ZoneInfo(self.timezone))
        except Exception:  # pragma: no cover - a bad tz name falls back to UTC, never to "open"
            local = moment.astimezone(dt.UTC)
        return local.weekday() in self.weekdays and self.open_hour <= local.hour < self.close_hour


@dataclass(frozen=True, slots=True)
class PhoneRoute:
    """Everything one dialled number means. Stored per tenant, never guessed from the call."""

    did: str
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None
    route_type: RouteType
    persona: PersonaRoute
    agent_profile_version: int | None = None
    language: str = "ar-EG"
    hours: BusinessHours | None = None
    fallback_did: str | None = None
    handoff_queue: str | None = None
    recording: RecordingMode = RecordingMode.OFF
    active: bool = True


class DIDRouter:
    """Resolves the dialled number to a route, or refuses to invent one."""

    def __init__(self, routes: Mapping[str, PhoneRoute]) -> None:
        self._routes = {self._normalise(did): route for did, route in routes.items()}

    @staticmethod
    def _normalise(did: str) -> str:
        return "".join(ch for ch in did if ch.isdigit() or ch == "+")

    def resolve(self, did: str) -> PhoneRoute:
        route = self._routes.get(self._normalise(did))
        if route is None:
            raise NotFoundError("this number is not routed to any shop")
        if not route.active:
            raise PermissionDeniedError("this number is not accepting calls")
        return route
