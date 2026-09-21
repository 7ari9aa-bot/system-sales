"""§146 — Field-level authorization.

Some fields are more sensitive than others. A customer service rep may see a
customer's name and phone, but not their internal margin or supplier cost.
A platform admin debugging a webhook never sees PII at all.

This module provides a declarative way to redact fields based on the caller's
role. The rule: the backend decides what the frontend may see — UI visibility
is NOT security (§12).
"""

from __future__ import annotations

from typing import Any

# Fields that are PII — redacted for anyone without the pii:read permission.
PII_FIELDS: frozenset[str] = frozenset({
    "phone",
    "email",
    "address",
    "date_of_birth",
    "national_id",
    "payment_method",
    "card_number",
    "card_last4",
    "bank_account",
})

# Fields that are internal — redacted for anyone without the internal:read permission.
INTERNAL_FIELDS: frozenset[str] = frozenset({
    "supplier_cost",
    "internal_margin",
    "cost",
    "profit",
    "markup",
    "wholesale_price",
    "internal_notes",
    "internal_tags",
})

# Fields that are secret — never exposed through the API, only through SecretStorePort.
SECRET_FIELDS: frozenset[str] = frozenset({
    "password_hash",
    "api_key",
    "access_token",
    "refresh_token",
    "webhook_secret",
    "credentials",
    "secret_value",
    "vault_key",
})


def redact_fields(
    data: dict[str, Any],
    *,
    permission_codes: set[str],
    fields_to_redact: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Return a copy of *data* with sensitive fields replaced by None.

    By default, redacts PII fields unless the caller has ``pii:read``, and
    internal fields unless they have ``internal:read``. Secret fields are
    ALWAYS redacted.
    """
    result = dict(data)
    can_read_pii = "pii:read" in permission_codes
    can_read_internal = "internal:read" in permission_codes

    # Always redact secret fields
    for field in SECRET_FIELDS:
        if field in result:
            result[field] = None

    if fields_to_redact is None:
        # Default: redact PII + internal based on permissions
        if not can_read_pii:
            for field in PII_FIELDS:
                if field in result:
                    result[field] = None
        if not can_read_internal:
            for field in INTERNAL_FIELDS:
                if field in result:
                    result[field] = None
    else:
        # Custom redaction set
        for field in fields_to_redact:
            if field in result:
                result[field] = None

    return result


def redact_customer(
    customer_dict: dict[str, Any],
    *,
    permission_codes: set[str],
) -> dict[str, Any]:
    """Redact PII from a customer dict based on the caller's permissions (§146)."""
    return redact_fields(customer_dict, permission_codes=permission_codes)


def redact_order(
    order_dict: dict[str, Any],
    *,
    permission_codes: set[str],
) -> dict[str, Any]:
    """Redact internal fields (cost, margin) from an order dict (§146)."""
    return redact_fields(order_dict, permission_codes=permission_codes)
