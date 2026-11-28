"""Shared dependencies and helpers for customer routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.contact_norm import normalize_email, normalize_phone
from app.modules.identity.deps import TenantContext, require_permission

WriteCtx = Annotated[TenantContext, Depends(require_permission("customers:write"))]
# P4 — the seeded matrix (scripts/provision.py ROLE_MATRIX) grants
# ``customers:read`` and ``customers:write`` as separate codes, so a read that
# resolved tenancy only (``TenantCtxDep``) let any member of the tenant pull the
# whole customer book. The five customer reads are gated on the read code now;
# the settings-screen read below is gated on ``settings:read`` for the same
# reason — its three siblings in this file already required ``settings:write``.
ReadCtx = Annotated[TenantContext, Depends(require_permission("customers:read"))]
SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]

# The contact report renames a phone before it reports it, and §146 redacts by
# FIELD NAME — so the renamed ones have to be listed alongside PII_FIELDS.
_EXTRA_PHONE_FIELDS = frozenset({"legacy_raw", "suspected_phone", "canonical_phone"})


def _customer_summary(customer, *, permission_codes: set[str] | None = None) -> dict:
    """Serialize a customer — §146: PII fields redacted without pii:read permission."""
    from app.core.field_auth import redact_customer

    raw = {
        "id": str(customer.id),
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "lifetime_value": str(customer.lifetime_value),
        "is_blocked": bool(customer.is_blocked),
    }
    if permission_codes is None:
        return raw
    return redact_customer(raw, permission_codes=permission_codes)


def _redact_issue_item(item: dict, ctx: TenantContext) -> dict:
    """§146 on a queue item — every phone column, including the ones the
    backfill RENAMED (``legacy_raw``/``suspected_phone``/``canonical_phone``),
    redacted unless the caller holds ``pii:read``. The redaction set is only
    applied when it must be: ``redact_fields`` with an explicit set redacts
    UNCONDITIONALLY, so passing it for a ``pii:read`` caller would hide the
    very values the operator is there to judge."""
    from app.core.field_auth import PII_FIELDS, redact_fields

    if "pii:read" in ctx.permission_codes:
        return dict(item)
    return redact_fields(
        item,
        permission_codes=ctx.permission_codes,
        fields_to_redact=PII_FIELDS | _EXTRA_PHONE_FIELDS,
    )


def _canonicalize_contact_fields(fields: dict) -> dict:
    """M12: the ``If-Match`` branch must store canonical contacts too.

    That branch writes through ``apply_versioned_update`` — plain column values,
    straight into one UPDATE — so it skipped the normalization the service does,
    and a local spelling typed into a drawer still recreated the duplicate M12
    exists to remove. ``phone`` is a uniqueness key, so an unparseable value
    raises here exactly as it does in the service
    (``ContactNormalizationError`` is the project's own 400).

    Only this branch: the service re-reads the RAW typing to match legacy rows
    that still hold it, so canonicalizing before that call would blind it.
    """
    if fields.get("phone") is not None:
        fields["phone"] = normalize_phone(fields["phone"])
    if fields.get("email") is not None:
        fields["email"] = normalize_email(fields["email"])
    return fields
