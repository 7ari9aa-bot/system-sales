"""TenantSettingsService — currency and timezone management (§47).

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy import select

from app.core.country import country_refusal, get_country
from app.core.currency import storage_refusal
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.platform.identity.dialects import dialect_refusal
from app.platform.identity.models import Tenant
from app.platform.identity.services._common import _record_audit

#: ``tenants.name`` is ``VARCHAR(255)``; bound it here so an over-long rename is a
#: 400 that explains itself instead of a 500 from the column.
_NAME_MAX_LEN = 255

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
    """§47 — the commercial settings of a tenant: name, currency and timezone."""

    @staticmethod
    async def set_name(
        session,
        tenant_id: uuid.UUID,
        name: str,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Rename the workspace: the shop's own name, not a person's.

        The name is printed on receipts and stamped into every audit row the
        shop writes, so it is stored cleaned — surrounding and repeated
        whitespace collapses — and a name that is only whitespace is refused
        (400) rather than becoming an unnamed shop. Renaming is a LABEL change:
        nothing keys off the name (the slug does), so reports, orders and stock
        keep pointing at the same rows after a rename.
        """
        cleaned = " ".join((name or "").split())
        if not cleaned:
            raise ValidationError("a workspace name cannot be empty")
        if len(cleaned) > _NAME_MAX_LEN:
            raise ValidationError(f"a workspace name must be at most {_NAME_MAX_LEN} characters")

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        previous = tenant.name
        if previous == cleaned:
            return tenant

        tenant.name = cleaned
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.name_changed",
            "tenant",
            tenant.id,
            before={"name": previous},
            after={"name": cleaned},
        )
        await session.flush()
        return tenant

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

    @staticmethod
    async def set_dialect(
        session,
        tenant_id: uuid.UUID,
        dialect: str | None,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Declare the Arabic dialect the owner's assistant answers in.

        The list is closed (``identity.dialects.CHOICES``): anything else is refused (400) rather
        than stored, and empty clears the choice back to the currency's dialect. The change is
        audited through the same lineage as currency and timezone."""
        # the list is exact: "gulf " is not "gulf", so the text is compared as given, never trimmed
        candidate = dialect or ""
        refusal = dialect_refusal(candidate)
        if refusal is not None:
            raise ValidationError(refusal)

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        previous = tenant.dialect
        wanted = candidate or None
        if previous == wanted:
            return tenant

        tenant.dialect = wanted
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.dialect_changed",
            "tenant",
            tenant.id,
            before={"dialect": previous},
            after={"dialect": wanted},
        )
        await session.flush()
        return tenant

    @staticmethod
    async def set_country(
        session,
        tenant_id: uuid.UUID,
        country_code: str,
        *,
        actor_user_id: uuid.UUID | None = None,
        sync_defaults: bool = True,
    ) -> Tenant:
        """Set the workspace country/market (ISO 3166-1 alpha-2, e.g. 'EG', 'SA').

        Validates against app.core.country.SUPPORTED_COUNTRIES.
        If sync_defaults is True and the tenant has not traded orders in another currency,
        currency, timezone and dialect are automatically aligned to the new market.
        """
        candidate = (country_code or "").strip().upper()
        refusal = country_refusal(candidate)
        if refusal is not None:
            raise ValidationError(refusal)

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")

        previous = tenant.country_code
        if previous == candidate:
            return tenant

        country = get_country(candidate)
        before_audit = {"country_code": previous}
        after_audit = {"country_code": candidate}

        tenant.country_code = candidate

        if sync_defaults and country:
            # Check if trading history blocks currency change
            if tenant.currency != country.currency:
                traded = (
                    await session.execute(
                        sa.text(
                            "SELECT 1 FROM orders "
                            "WHERE tenant_id = :tid AND currency <> :code LIMIT 1"
                        ),
                        {"tid": tenant_id, "code": country.currency},
                    )
                ).first()
                if traded is None:
                    before_audit["currency"] = tenant.currency
                    after_audit["currency"] = country.currency
                    tenant.currency = country.currency

            if country.default_timezone:
                before_audit["timezone"] = tenant.timezone
                after_audit["timezone"] = country.default_timezone
                tenant.timezone = country.default_timezone

            if country.default_dialect:
                before_audit["dialect"] = tenant.dialect
                after_audit["dialect"] = country.default_dialect
                tenant.dialect = country.default_dialect

        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.country_changed",
            "tenant",
            tenant.id,
            before=before_audit,
            after=after_audit,
        )
        await session.flush()
        return tenant
