"""Who a voice session speaks as, and which tools it may reach.

The session capability is the whole authorization story in one frozen value: the tenant it is
bound to, the principal behind it, the persona the backend chose, the scopes it actually holds,
and when it stops being valid. It is issued once, at session creation, from the authenticated
principal — never from a request body, never from anything the model said (invariants 2, 3, 8).

Two things are deliberately hard here:

* A merchant session's scopes are the INTERSECTION of what the persona allows and what the user
  holds in the dashboard. A cashier who cannot open the expenses screen cannot have the expenses
  read aloud to them.
* The tool gateway re-checks every call. The capability says what was issued; the gateway decides
  what is executable right now, because a user's permission can be revoked mid-call (invariant 7).

Refusals raise ``PermissionDeniedError`` from the core error module so the router answers 403 and
the attempt is auditable, rather than the tool quietly returning empty data that the model then
narrates as "you have no orders".
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from dataclasses import dataclass, field
from typing import Final

from app.core.errors import PermissionDeniedError
from app.modules.voice.domain.personas import (
    CUSTOMER_FORBIDDEN_SCOPES,
    Effect,
    Persona,
    PersonaType,
    PrincipalType,
    persona_for,
)


class AuthenticationLevel(enum.IntEnum):
    """How much of a customer's private data the session has earned.

    The numbers matter: they are compared, and a level is only ever raised by the identity
    verification engine, never by the agent deciding it is probably fine.
    """

    ANONYMOUS = 0
    IDENTIFIED = 1
    VERIFIED = 2
    ACTION_AUTHORIZED = 3


class ChannelType(enum.StrEnum):
    WEB_VOICE = "web_voice"
    CHAT_VOICE = "chat_voice"
    PSTN = "pstn"
    WHATSAPP_VOICE = "whatsapp_voice"
    MOBILE = "mobile"


@dataclass(frozen=True, slots=True)
class VoiceTool:
    """One callable the agent may ask for, with the scope it spends and its effect on the world."""

    name: str
    effect: Effect
    scope: str
    write: bool = False
    cancellable: bool = True


# A representative registry, not the full catalogue: the point is that every tool declares its
# scope and effect so the gateway can refuse without knowing what the tool does. Domain tools are
# added here as phases land, each one naming the scope it needs.
VOICE_TOOLS: Final[dict[str, VoiceTool]] = {
    tool.name: tool
    for tool in (
        VoiceTool("orders.read", Effect.READ, "orders:read"),
        VoiceTool("inventory.read", Effect.READ, "inventory:read"),
        VoiceTool("catalog.read", Effect.READ, "catalog:read"),
        VoiceTool("analytics.read", Effect.READ, "analytics:read"),
        VoiceTool("expenses.read", Effect.READ, "expenses:read"),
        VoiceTool("customers.read", Effect.READ, "customers:read"),
        VoiceTool("store.info", Effect.READ, "store.info:read"),
        VoiceTool("catalog.public", Effect.READ, "catalog.published:read"),
        VoiceTool("customer.own_orders", Effect.READ, "customer.own_orders:read"),
        VoiceTool("customer.own_returns", Effect.READ, "customer.own_returns:read"),
        VoiceTool("support.knowledge", Effect.READ, "support.knowledge:read"),
        # A write tool exists in the vocabulary so the gateway's refusal is testable: no persona
        # in V1 carries ``write_tools``, so this can never execute.
        VoiceTool(
            "orders.create",
            Effect.APPROVED_CUSTOMER_ACTION,
            "customer.own_orders:write",
            write=True,
            cancellable=False,
        ),
    )
}


# نطاق الدخول للمساعد الصوتي: بيفتح الجلسة، ومش بيقرأ أي بيانات لوحده.
ENTRY_SCOPE: Final = "assistant:use"


@dataclass(frozen=True, slots=True)
class SessionCapability:
    """What one voice session may do, fixed at creation and re-checked on every call."""

    session_id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None
    principal_type: PrincipalType
    principal_id: uuid.UUID | None
    persona: PersonaType
    channel: ChannelType
    authentication_level: AuthenticationLevel
    scopes: frozenset[str]
    policy_version: str
    agent_version_id: uuid.UUID | None
    issued_at: dt.datetime
    expires_at: dt.datetime
    conversation_id: uuid.UUID | None = None
    ai_chat_thread_id: uuid.UUID | None = None
    call_id: uuid.UUID | None = None
    trace_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def is_live(self, now: dt.datetime) -> bool:
        return now < self.expires_at

    def covers(self, tool: VoiceTool) -> bool:
        """Does this capability carry the scope and effect the tool needs?"""
        return tool.scope in self.scopes


def resolve_capability(
    *,
    principal_type: PrincipalType,
    principal_id: uuid.UUID | None,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    held_scopes: frozenset[str],
    channel: ChannelType,
    session_id: uuid.UUID | None = None,
    authentication_level: AuthenticationLevel = AuthenticationLevel.ANONYMOUS,
    policy_version: str = "v1",
    agent_version_id: uuid.UUID | None = None,
    issued_at: dt.datetime | None = None,
    ttl_seconds: int = 3600,
) -> SessionCapability:
    """Issue the capability for a session, or refuse to open one.

    ``held_scopes`` are what the authenticated principal already holds in the dashboard. For a
    merchant user the session gets their intersection with the persona; a merchant user holding
    nothing that a voice assistant can read is refused outright instead of being given a session
    that can only apologise.
    """
    persona = persona_for(principal_type)
    now = issued_at or dt.datetime.now(dt.UTC)

    if principal_type is PrincipalType.MERCHANT_USER:
        if principal_id is None:
            raise PermissionDeniedError("merchant voice needs an identified user")
        granted = persona.read_scopes & held_scopes
        # الدخول للصوت مش قراءة بيانات: «assistant:use» لوحدها كفاية لفتح جلسة، والقراءة
        # نفسها بتفضل مقصورة على نطاق البيرسونا + اللي المستخدم شايله فعلاً. من غير كده
        # كان فتح المكالمة بيطلب orders:read، وده عكس القرار المعماري.
        if not granted and ENTRY_SCOPE not in held_scopes:
            raise PermissionDeniedError("this user holds no shop scope a voice assistant may read")
        if ENTRY_SCOPE in held_scopes:
            granted = frozenset(granted | {ENTRY_SCOPE})
        level = AuthenticationLevel.VERIFIED
    else:
        # A customer's public scopes need no proof; own-orders/own-returns are added only when
        # verification reached VERIFIED. Caller ID alone never gets here with VERIFIED.
        granted = {scope for scope in persona.read_scopes if not scope.startswith("customer.own_")}
        if authentication_level >= AuthenticationLevel.VERIFIED:
            granted |= {s for s in persona.read_scopes if s.startswith("customer.own_")}
        granted = frozenset(granted)
        level = authentication_level

    forbidden = (
        granted & CUSTOMER_FORBIDDEN_SCOPES
        if persona.type is PersonaType.CUSTOMER_AGENT
        else frozenset()
    )
    if forbidden:  # pragma: no cover - the persona sets above make this unreachable
        raise PermissionDeniedError(f"customer voice may never hold {sorted(forbidden)}")

    return SessionCapability(
        session_id=session_id or uuid.uuid4(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        principal_type=principal_type,
        principal_id=principal_id,
        persona=persona.type,
        channel=channel,
        authentication_level=level,
        scopes=frozenset(granted),
        policy_version=policy_version,
        agent_version_id=agent_version_id,
        issued_at=now,
        expires_at=now + dt.timedelta(seconds=ttl_seconds),
    )


class ToolGateway:
    """The only door between a model's tool call and a domain service."""

    def __init__(self, tools: dict[str, VoiceTool] | None = None) -> None:
        self._tools = dict(VOICE_TOOLS if tools is None else tools)

    def authorize(
        self,
        capability: SessionCapability,
        tool_name: str,
        *,
        tenant_id: uuid.UUID | None = None,
        subject_id: uuid.UUID | None = None,
        now: dt.datetime | None = None,
    ) -> VoiceTool:
        """Return the tool when this session may run it; raise otherwise.

        The checks are ordered cheapest-and-most-fundamental first: an unknown tool, an expired
        session, a different tenant, a persona that cannot write, an effect it does not hold, and
        finally the scope. Every branch is a 403 with a reason an operator can read.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            raise PermissionDeniedError(f"unknown voice tool {tool_name!r}")

        persona: Persona = persona_for(capability.principal_type)
        moment = now or dt.datetime.now(dt.UTC)
        if not capability.is_live(moment):
            raise PermissionDeniedError("voice session has expired")

        if tenant_id is not None and tenant_id != capability.tenant_id:
            raise PermissionDeniedError("tool call targets another tenant")

        if tool.write and not persona.write_tools:
            raise PermissionDeniedError(
                f"{persona.type.value} has no write tools; {tool_name} is refused"
            )
        if not persona.allows_effect(tool.effect):
            raise PermissionDeniedError(f"{persona.type.value} may not cause {tool.effect.value}")
        if not capability.covers(tool):
            raise PermissionDeniedError(f"{persona.type.value} session does not hold {tool.scope}")
        # A customer-scoped tool names whose data it reads. Holding customer.own_orders is a
        # permission to read MY orders, not a permission to name someone else's id (invariant 6).
        if tool.scope.startswith("customer.own_") and subject_id != capability.principal_id:
            raise PermissionDeniedError(
                f"{tool_name} may only read the verified customer's own data"
            )
        return tool

    def authorized_tools(self, capability: SessionCapability) -> tuple[str, ...]:
        """What the model may be told about at all.

        The tool list handed to a provider is already filtered, so a model cannot call what it was
        never shown — but the gateway still re-checks, because the list is a hint and the call is
        the fact.
        """
        persona = persona_for(capability.principal_type)
        return tuple(
            sorted(
                name
                for name, tool in self._tools.items()
                if not (tool.write and not persona.write_tools)
                and persona.allows_effect(tool.effect)
                and capability.covers(tool)
            )
        )


def assert_same_tenant(capability: SessionCapability, tenant_id: uuid.UUID) -> None:
    """A session never changes shop mid-call (invariant 8): open a new one instead."""
    if tenant_id != capability.tenant_id:
        raise PermissionDeniedError(
            "a voice session cannot move to another tenant; close it and open a new one"
        )
