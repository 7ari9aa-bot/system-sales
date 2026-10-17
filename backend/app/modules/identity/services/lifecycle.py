"""TenantLifecycleService — §48 state machine, capability policies, transition logic.

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.identity.models import Tenant
from app.modules.identity.services._common import (
    _now,
    _record_audit,
    _record_security_event,
)

# --- tenant lifecycle (spec §48) -------------------------------------------
#
# State machine — every transition is validated, never assigned directly:
#
#   provisioning ──> trial ──> active <──> past_due ──> grace
#         │            │         │  ▲          │           │
#         └──> active ─┘         │  └──────────┘           │
#                               │  (payment received)     │
#                               ▼                         ▼
#                           suspended ──> offboarding ──> deleted [terminal]
#
# `is_active` (the coarse flag) is derived from the state via
# TenantLifecycleService.is_coarse_active. The two can never disagree because
# transition() is the only writer of both.
TENANT_LIFECYCLE_STATES: tuple[str, ...] = (
    "provisioning",
    "trial",
    "active",
    "past_due",
    "grace",
    "suspended",
    "offboarding",
    "deleted",
)

TENANT_INITIAL_STATE = "provisioning"

# current state -> states it may move to. `deleted` is terminal.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "provisioning": frozenset({"trial", "active", "deleted"}),
    "trial": frozenset({"active", "past_due", "suspended", "offboarding", "deleted"}),
    "active": frozenset({"past_due", "suspended", "offboarding", "deleted"}),
    "past_due": frozenset({"active", "grace", "suspended", "offboarding", "deleted"}),
    "grace": frozenset({"active", "suspended", "offboarding", "deleted"}),
    "suspended": frozenset({"active", "offboarding", "deleted"}),
    "offboarding": frozenset({"active", "deleted"}),
    "deleted": frozenset(),
}

# Lifecycle targets that RESTORE service or steer billing (external audit
# finding 1): anything that takes a tenant out of past_due/grace/suspension
# re-opens the money firehose, and `deleted` is the irreversible half of the
# same authority. Those transitions are platform-admin-only.
PLATFORM_ONLY_LIFECYCLE_TARGETS: frozenset[str] = frozenset(
    {"active", "past_due", "grace", "deleted"}
)
# The only target a non-platform-admin may request through the route.
TENANT_REQUESTABLE_LIFECYCLE_TARGETS: frozenset[str] = frozenset({"offboarding"})

# States in which the tenant still operates normally.
TENANT_OPERATIONAL_STATES: frozenset[str] = frozenset(
    {"provisioning", "trial", "active", "past_due", "grace"}
)

# Entering one of these states takes capability away from the tenant.
_REASON_REQUIRED: frozenset[str] = frozenset({"suspended", "offboarding", "deleted"})

# §67: security event types for lifecycle changes.
_LIFECYCLE_SECURITY_EVENTS: dict[str, str] = {
    "suspended": "tenant_suspended",
    "offboarding": "tenant_offboarding_started",
    "deleted": "tenant_deleted",
}

# How long a tenant keeps working after payment fails, and how long after
# offboarding starts the data is retained before deletion.
GRACE_PERIOD_DAYS = 14
OFFBOARDING_RETENTION_DAYS = 30


@dataclass(frozen=True, slots=True)
class TenantCapabilityPolicy:
    """What a tenant is allowed to do in a given lifecycle state (§48)."""

    allows_login: bool
    allows_api: bool
    allows_ai: bool
    allows_channels: bool
    allows_automation: bool
    allows_data_access: bool


_FULL = TenantCapabilityPolicy(
    allows_login=True,
    allows_api=True,
    allows_ai=True,
    allows_channels=True,
    allows_automation=True,
    allows_data_access=True,
)
_SETUP = TenantCapabilityPolicy(
    allows_login=True,
    allows_api=True,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=True,
)
_SUSPENDED = TenantCapabilityPolicy(
    allows_login=False,
    allows_api=False,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=True,
)
_OFFBOARDING = TenantCapabilityPolicy(
    allows_login=True,
    allows_api=False,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=True,
)
_DELETED = TenantCapabilityPolicy(
    allows_login=False,
    allows_api=False,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=False,
)

STATE_POLICIES: dict[str, TenantCapabilityPolicy] = {
    "provisioning": _SETUP,
    "trial": _FULL,
    "active": _FULL,
    "past_due": _FULL,
    "grace": _FULL,
    "suspended": _SUSPENDED,
    "offboarding": _OFFBOARDING,
    "deleted": _DELETED,
}


class TenantLifecycleService:
    """Owns the §48 tenant lifecycle: transitions, timestamps and audit."""

    @staticmethod
    async def get(session, tenant_id: uuid.UUID, *, for_update: bool = False) -> Tenant:
        statement = select(Tenant).where(Tenant.id == tenant_id)
        if for_update:
            statement = statement.with_for_update()
        tenant = (await session.execute(statement)).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        return tenant

    @staticmethod
    def policy_for(state: str) -> TenantCapabilityPolicy:
        """The capability policy for a state (unknown state is a bug, not a 404)."""
        try:
            return STATE_POLICIES[state]
        except KeyError:
            raise ValidationError(f"unknown tenant lifecycle state: {state}") from None

    @staticmethod
    def is_state(tenant: Tenant, state: str) -> bool:
        """Callers ask this instead of poking `is_active`."""
        return tenant.lifecycle_state == state

    @staticmethod
    def is_coarse_active(state: str) -> bool:
        """The `is_active` value a state maps to (single source of the rule)."""
        return state in TENANT_OPERATIONAL_STATES

    @staticmethod
    async def transition(
        session,
        tenant_id: uuid.UUID,
        target: str,
        *,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Move a tenant to `target`, or refuse with a clear conflict."""
        if not isinstance(target, str) or target not in STATE_POLICIES:
            raise ValidationError(f"unknown tenant lifecycle state: {target!r}")
        if reason is not None and not isinstance(reason, str):
            raise ValidationError(f"a reason must be a string, got {type(reason).__name__}")
        if target in _REASON_REQUIRED and not (reason or "").strip():
            raise ValidationError(f"a reason is required to move a tenant to {target}")

        tenant = await TenantLifecycleService.get(session, tenant_id, for_update=True)
        current = tenant.lifecycle_state
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            if allowed:
                hint = f" (allowed: {', '.join(sorted(allowed))})"
            else:
                hint = " — deleted is terminal"
            raise ConflictError(f"cannot move a {current} tenant to {target}{hint}")

        was_active = tenant.is_active
        now = _now()
        tenant.lifecycle_state = target
        tenant.is_active = TenantLifecycleService.is_coarse_active(target)
        tenant.status_reason = reason
        tenant.suspended_at = now if target == "suspended" else None
        tenant.grace_ends_at = (
            now + timedelta(days=GRACE_PERIOD_DAYS) if target == "grace" else None
        )
        tenant.deletion_scheduled_at = (
            now + timedelta(days=OFFBOARDING_RETENTION_DAYS) if target == "offboarding" else None
        )

        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.lifecycle_changed",
            "tenant",
            tenant.id,
            before={"lifecycle_state": current, "is_active": was_active},
            after={
                "lifecycle_state": target,
                "is_active": tenant.is_active,
                "reason": reason,
            },
        )
        event_type = _LIFECYCLE_SECURITY_EVENTS.get(target)
        if event_type is None and target == "active" and current in _REASON_REQUIRED:
            event_type = "tenant_reactivated"
        await _record_security_event(
            event_type or "tenant_lifecycle_changed",
            details={"from": current, "to": target, "reason": reason},
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
        )
        await session.flush()
        return tenant
