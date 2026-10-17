"""TenantSettingsService — currency and timezone management (§47).

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy import select

from app.core.currency import storage_refusal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.identity.models import Tenant
from app.modules.identity.services._common import _record_audit

#: ``tenants.timezone`` is ``VARCHAR(64)`` with a shape CHECK (migration
#: e3b7d2a9c4f1). Bound the same way here, so an owner gets a 400 that explains
#: itself rather than a 500 from the constraint.
_TIMEZONE_MAX_LEN = 64
_TIMEZONE_SHAPE = re.compile(r"[A-Za-z][A-Za-z0-9_/+-]*(?:/[A-Za-z0-9_+-]+)*")


def timezone_refusal(value: str | None) -> str | None:
    """Why this is not a zone the tenant may count its days in, or ``None``.

    The §47 currency precedent, with ``zoneinfo`` in place of the ISO table: a
    name the runtime cannot resolve is refused, never stored and never rounded
    down to "close enough". The database check only bounds the SHAPE (tzdata
    lives in Python, not in Postgres), so this function is where resolvability
    is actually asserted — and `analytics.timekit.resolve_timezone` re-checks it
    on every read, so a stored name that ever stops resolving fails closed
    instead of silently bucketing a Cairo shop in UTC.
    """
    name = (value or "").strip()
    if not name:
        return "a timezone is required (an IANA name such as 'Africa/Cairo')"
    if len(name) > _TIMEZONE_MAX_LEN or not _TIMEZONE_SHAPE.fullmatch(name):
        return f"'{name}' is not shaped like an IANA timezone name (e.g. 'Africa/Cairo')"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        return f"'{name}' is not a timezone this system can resolve: {exc}"
    return None


class TenantSettingsService:
    """§47 — the commercial settings of a tenant: currency and timezone."""

    @staticmethod
    async def set_currency(
        session,
        tenant_id: uuid.UUID,
        currency: str,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        code = (currency or "").strip().upper()
        refusal = storage_refusal(code)
        if refusal is not None:
            raise ValidationError(refusal)

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        previous = (tenant.currency or "").upper()
        if previous == code:
            return tenant

        traded = (
            await session.execute(
                sa.text(
                    "SELECT 1 FROM orders WHERE tenant_id = :tid AND currency <> :code LIMIT 1"
                ),
                {"tid": tenant_id, "code": code},
            )
        ).first()
        if traded is not None:
            raise ConflictError(
                f"this tenant has already traded in {previous}: orders keep the "
                f"currency they were sold in, so the default cannot move to {code} "
                "out from under them"
            )

        tenant.currency = code
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.currency_changed",
            "tenant",
            tenant.id,
            before={"currency": previous},
            after={"currency": code},
        )
        await session.flush()
        return tenant

    @staticmethod
    async def set_timezone(
        session,
        tenant_id: uuid.UUID,
        timezone: str | None,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        """§47/M10 remainder: declare the calendar day this merchant counts in."""
        zone = (timezone or "").strip()
        if zone:
            refusal = timezone_refusal(zone)
            if refusal is not None:
                raise ValidationError(refusal)

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        previous = tenant.timezone
        if (previous or "") == zone:
            return tenant

        tenant.timezone = zone or None
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.timezone_changed",
            "tenant",
            tenant.id,
            before={"timezone": previous},
            after={"timezone": zone or None},
        )
        await session.flush()
        return tenant
