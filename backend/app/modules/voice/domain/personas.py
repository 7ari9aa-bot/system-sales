"""The two voice principals, and the powers each one may never have.

Merchant voice and customer voice are not one agent with a different prompt. They are two
security principals that happen to share the audio runtime: the backend picks the persona from
the authenticated principal (invariant 2), and the model never chooses it. A tool outside the
persona's set is refused by the tool gateway even when the model asks for it (invariant 7).

Nothing here grants a write. The merchant assistant is read-only in the target version
(invariant 5), and the customer agent's writes are approved action workflows that do not exist
yet (invariant 6) — the vocabulary below has a name for them so the boundary is explicit, not so
they can be switched on by accident.

The scope strings are the only currency a voice agent may spend: they are matched against the
scopes a merchant user already holds, so a staff member who cannot see expenses in the dashboard
cannot hear them read aloud either.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


class PrincipalType(enum.StrEnum):
    """Who is on the other end of the audio, as the session auth layer proved it."""

    MERCHANT_USER = "merchant_user"
    CUSTOMER = "customer"
    ANONYMOUS = "anonymous"


class PersonaType(enum.StrEnum):
    MERCHANT_ASSISTANT = "merchant_assistant"
    CUSTOMER_AGENT = "customer_agent"


class Effect(enum.StrEnum):
    """What a tool is allowed to do to the world, independent of who calls it."""

    READ = "READ"
    APPROVED_CUSTOMER_ACTION = "APPROVED_CUSTOMER_ACTION"


class DataScope(enum.StrEnum):
    AUTHORIZED_SHOP_DATA = "AUTHORIZED_SHOP_DATA"
    PUBLIC_OR_VERIFIED_CUSTOMER_DATA = "PUBLIC_OR_VERIFIED_CUSTOMER_DATA"


# The twelve business domains a merchant may hear about, each behind the permission the dashboard
# already enforces. "authorized" is doing the work: the capability carries the intersection of
# these and what the signed-in user actually holds.
MERCHANT_READ_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "catalog:read",
        "inventory:read",
        "orders:read",
        "customers:read",
        "conversations:read",
        "sales:read",
        "marketing:read",
        "analytics:read",
        "expenses:read",
        "purchasing:read",
        "billing:read",
        "staff:read",
    }
)

# What a buyer may reach without proving anything beyond the shop they dialled. Own-orders and
# own-returns are listed because the scope exists; the capability only carries them once the
# identity verification level allows it (see ``identity_verification.py``).
CUSTOMER_READ_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "catalog.published:read",
        "pricing.availability:read",
        "store.info:read",
        "support.knowledge:read",
        "customer.own_orders:read",
        "customer.own_returns:read",
    }
)

# Scopes that must never reach a customer, even if a persona were misconfigured: the analytics
# and money of the shop are not a customer's business, and naming them here makes the refusal
# testable rather than implied.
CUSTOMER_FORBIDDEN_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "analytics:read",
        "expenses:read",
        "billing:read",
        "staff:read",
        "customers:read",
        "marketing:read",
        "purchasing:read",
    }
)


@dataclass(frozen=True, slots=True)
class Persona:
    """One security principal's whole surface, as a value the gateway can check."""

    type: PersonaType
    principal_types: frozenset[PrincipalType]
    allowed_effects: frozenset[Effect]
    data_scope: DataScope
    read_scopes: frozenset[str]
    write_tools: bool
    cross_tenant_access: bool
    cross_customer_access: bool

    def allows_effect(self, effect: Effect) -> bool:
        return effect in self.allowed_effects

    def allows_scope(self, scope: str) -> bool:
        return scope in self.read_scopes


MERCHANT_ASSISTANT: Final[Persona] = Persona(
    type=PersonaType.MERCHANT_ASSISTANT,
    principal_types=frozenset({PrincipalType.MERCHANT_USER}),
    allowed_effects=frozenset({Effect.READ}),
    data_scope=DataScope.AUTHORIZED_SHOP_DATA,
    read_scopes=MERCHANT_READ_SCOPES,
    write_tools=False,
    cross_tenant_access=False,
    cross_customer_access=False,
)

CUSTOMER_AGENT: Final[Persona] = Persona(
    type=PersonaType.CUSTOMER_AGENT,
    principal_types=frozenset({PrincipalType.CUSTOMER, PrincipalType.ANONYMOUS}),
    allowed_effects=frozenset({Effect.READ, Effect.APPROVED_CUSTOMER_ACTION}),
    data_scope=DataScope.PUBLIC_OR_VERIFIED_CUSTOMER_DATA,
    read_scopes=CUSTOMER_READ_SCOPES,
    write_tools=False,  # V1: the action gateway exists, no action is switched on
    cross_tenant_access=False,
    cross_customer_access=False,
)

VOICE_PERSONAS: Final[MappingProxyType[PersonaType, Persona]] = MappingProxyType(
    {
        PersonaType.MERCHANT_ASSISTANT: MERCHANT_ASSISTANT,
        PersonaType.CUSTOMER_AGENT: CUSTOMER_AGENT,
    }
)


class PersonaResolutionError(Exception):
    """A principal that no voice persona may speak for, or a persona it may not use."""


def persona_for(principal: PrincipalType) -> Persona:
    """The persona this principal speaks through, decided here and nowhere else.

    An anonymous caller gets the customer agent because a shop's public catalogue is public; a
    customer gets it for the same reason plus whatever verification unlocks. A merchant user
    never falls back to the customer agent: a failed tenant resolution must end the session, not
    silently downgrade it to a persona with different data rules.
    """
    if principal in (PrincipalType.CUSTOMER, PrincipalType.ANONYMOUS):
        return CUSTOMER_AGENT
    if principal is PrincipalType.MERCHANT_USER:
        return MERCHANT_ASSISTANT
    raise PersonaResolutionError(f"no voice persona for principal {principal!r}")


def persona_by_type(persona: PersonaType) -> Persona:
    """Look a persona up by name — used when a stored session is re-read, never from a request."""
    try:
        return VOICE_PERSONAS[persona]
    except KeyError as exc:  # pragma: no cover - the enum makes this unreachable by name
        raise PersonaResolutionError(f"unknown voice persona {persona!r}") from exc
