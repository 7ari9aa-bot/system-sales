"""What a customer agent is allowed to know about the person on the line.

The builder is the last place where a wrong id could turn into someone else's order. It takes the
session capability, not a request body, and it keeps only records whose ``customer_id`` is the
verified principal. Anything else is dropped silently from the agent's view and counted, so the
refusal shows up in tests and metrics instead of in a transcript.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.errors import PermissionDeniedError
from app.modules.voice.domain.personas import PersonaType
from app.modules.voice.security.capabilities import (
    AuthenticationLevel,
    SessionCapability,
)


@dataclass(frozen=True, slots=True)
class OrderRef:
    order_id: uuid.UUID
    customer_id: uuid.UUID
    number: str
    status: str


@dataclass(frozen=True, slots=True)
class CustomerContext:
    tenant_id: uuid.UUID
    customer_id: uuid.UUID | None
    level: AuthenticationLevel
    channel: str
    conversation_id: uuid.UUID | None
    verification_method: str | None
    visible_orders: tuple[OrderRef, ...] = ()
    discussed_products: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    dropped_foreign_records: int = field(default=0)

    def brief(self) -> dict[str, object]:
        """The handoff summary staff see. It names no other customer and no payment detail."""
        return {
            "tenant_id": str(self.tenant_id),
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "verification": self.verification_method or "unverified",
            "level": int(self.level),
            "channel": self.channel,
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "orders": [order.number for order in self.visible_orders],
            "discussed_products": list(self.discussed_products),
            "policies": list(self.policy_refs),
        }


class CustomerContextBuilder:
    def build(
        self,
        *,
        capability: SessionCapability,
        conversation_id: uuid.UUID | None = None,
        discussed_products: tuple[str, ...] = (),
        policy_refs: tuple[str, ...] = (),
        orders: tuple[OrderRef, ...] = (),
        verification_method: str | None = None,
    ) -> CustomerContext:
        if capability.persona is not PersonaType.CUSTOMER_AGENT:
            raise PermissionDeniedError("customer context is built only for a customer session")

        may_read_orders = "customer.own_orders:read" in capability.scopes
        visible: list[OrderRef] = []
        dropped = 0
        for order in orders:
            if not may_read_orders or order.customer_id != capability.principal_id:
                dropped += 1
                continue
            visible.append(order)

        return CustomerContext(
            tenant_id=capability.tenant_id,
            customer_id=capability.principal_id,
            level=capability.authentication_level,
            channel=capability.channel.value,
            conversation_id=conversation_id,
            verification_method=verification_method,
            visible_orders=tuple(visible),
            discussed_products=tuple(discussed_products),
            policy_refs=tuple(policy_refs),
            dropped_foreign_records=dropped,
        )
