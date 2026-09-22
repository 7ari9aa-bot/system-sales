"""Per-tenant service tokens for the n8n adapter (spec §136).

The single global ``SERVICE_TOKEN_INTERNAL`` Bearer let any tenant's
automation act as any other tenant. These tokens replace it: per-tenant,
scoped, revocable, and stored only as a sha256 hex digest — the plaintext
is returned exactly once at issuance and never persisted. Verification is
a digest-equality lookup over fixed-length hashes, so the comparison is
constant-time by construction (the database never compares the presented
secret itself).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.platform.models import TenantServiceToken

# The two scopes the n8n adapter needs: presenting the token back on the
# n8n -> core callback, and authorising the core -> n8n trigger call.
SCOPE_AUTOMATION_CALLBACK = "automation:callback"
SCOPE_AUTOMATION_TRIGGER = "automation:trigger"
DEFAULT_SCOPES: tuple[str, ...] = (SCOPE_AUTOMATION_CALLBACK, SCOPE_AUTOMATION_TRIGGER)

_TOKEN_PREFIX = "tst_"
_OUTBOUND_TOKEN_NAME = "n8n-outbound"

# In-process cache of the OUTBOUND token per tenant. Plaintext cannot be
# re-read from the database (only the digest is stored), so the process
# that issued the token keeps it in memory; a restart issues a fresh one.
# Keyed by tenant_id — a token is never shared across tenants.
_outbound_tokens: dict[uuid.UUID, str] = {}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_token(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    scopes: list[str] | tuple[str, ...],
) -> str:
    """Issue a per-tenant service token; the plaintext is returned ONCE.

    Only the sha256 digest lands in the database. Stages the outbox event
    ``automation.service_token.issued`` in the caller's transaction.
    """
    plaintext = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    row = TenantServiceToken(
        tenant_id=tenant_id,
        name=name,
        token_hash=_digest(plaintext),
        scopes=list(scopes),
    )
    session.add(row)
    await session.flush()

    from app.core.events.writer import add_outbox_event

    await add_outbox_event(
        session,
        aggregate_type="tenant_service_token",
        aggregate_id=row.id,
        event_type="automation.service_token.issued",
        tenant_id=tenant_id,
        payload={"name": name, "scopes": list(scopes)},
        # TenantServiceToken has no VersionMixin; issuance is the row's
        # first state, so the aggregate version is the literal 1.
        aggregate_version=1,
    )
    return plaintext


async def verify_token(
    session: AsyncSession,
    token: str,
    *,
    tenant_id: uuid.UUID | None = None,
    required_scope: str | None = None,
) -> TenantServiceToken:
    """Verify a presented token; returns the token row when valid.

    Under FORCE RLS the row is only visible when the session's
    ``app.tenant_id`` matches the token's tenant, so a token presented
    under another tenant reads as nonexistent; ``tenant_id`` adds the
    same check explicitly for callers that are not RLS-bound. Revoked
    tokens and missing scopes are rejected. ``last_used_at`` is stamped
    on success.
    """
    row = (
        await session.execute(
            select(TenantServiceToken).where(TenantServiceToken.token_hash == _digest(token))
        )
    ).scalar_one_or_none()
    if row is None:
        raise PermissionDeniedError("invalid service token")
    if row.revoked_at is not None:
        raise PermissionDeniedError("service token revoked")
    if tenant_id is not None and row.tenant_id != tenant_id:
        raise PermissionDeniedError("service token does not belong to this tenant")
    if required_scope is not None and required_scope not in (row.scopes or []):
        raise PermissionDeniedError(f"service token missing scope: {required_scope}")
    row.last_used_at = datetime.now(UTC)
    await session.flush()
    return row


async def rotate_token(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    token_id: uuid.UUID,
    *,
    name: str | None = None,
    scopes: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Revoke ``token_id`` and issue its successor; plaintext returned ONCE.

    The successor links back via ``rotated_from_id`` so the rotation chain
    stays auditable.
    """
    row = await _get_token(session, tenant_id, token_id)
    plaintext = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    successor = TenantServiceToken(
        tenant_id=tenant_id,
        name=name or row.name,
        token_hash=_digest(plaintext),
        scopes=list(scopes) if scopes is not None else list(row.scopes or []),
        rotated_from_id=row.id,
    )
    row.revoked_at = datetime.now(UTC)
    session.add(successor)
    await session.flush()

    from app.core.events.writer import add_outbox_event

    await add_outbox_event(
        session,
        aggregate_type="tenant_service_token",
        aggregate_id=successor.id,
        event_type="automation.service_token.issued",
        tenant_id=tenant_id,
        payload={
            "name": successor.name,
            "scopes": list(successor.scopes or []),
            "rotated_from_id": str(row.id),
        },
        aggregate_version=1,  # no VersionMixin — the successor row is born at version 1.
    )
    await add_outbox_event(
        session,
        aggregate_type="tenant_service_token",
        aggregate_id=row.id,
        event_type="automation.service_token.revoked",
        tenant_id=tenant_id,
        payload={"name": row.name, "reason": "rotated", "successor_id": str(successor.id)},
        aggregate_version=1,  # no VersionMixin — revocation is one terminal transition.
    )
    return plaintext


async def revoke_token(
    session: AsyncSession, tenant_id: uuid.UUID, token_id: uuid.UUID
) -> TenantServiceToken:
    """Revoke a token (idempotent); stages ``automation.service_token.revoked``."""
    row = await _get_token(session, tenant_id, token_id)
    if row.revoked_at is not None:
        return row
    row.revoked_at = datetime.now(UTC)
    await session.flush()

    from app.core.events.writer import add_outbox_event

    await add_outbox_event(
        session,
        aggregate_type="tenant_service_token",
        aggregate_id=row.id,
        event_type="automation.service_token.revoked",
        tenant_id=tenant_id,
        payload={"name": row.name, "reason": "revoked"},
        aggregate_version=1,  # no VersionMixin — revocation is one terminal transition.
    )
    return row


async def get_or_issue_outbound_token(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    """The per-tenant token carried on core -> n8n calls (§136).

    Issued once per tenant and cached in-process (only the digest is in the
    database, so after a restart a fresh token is issued). NEVER falls back
    to the global ``SERVICE_TOKEN_INTERNAL`` — if issuance fails the error
    propagates to the caller.

    Revokes any still-active outbound token before issuing a new one: the
    in-process cache is gone after a restart but the old row is not, and
    without this every deploy left another live credential in the database
    (unbounded accumulation, nothing to revoke them through).
    """
    cached = _outbound_tokens.get(tenant_id)
    if cached is not None:
        return cached
    stale = (
        await session.execute(
            select(TenantServiceToken).where(
                TenantServiceToken.tenant_id == tenant_id,
                TenantServiceToken.name == _OUTBOUND_TOKEN_NAME,
                TenantServiceToken.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    for row in stale:
        await revoke_token(session, tenant_id, row.id)
    token = await issue_token(session, tenant_id, _OUTBOUND_TOKEN_NAME, DEFAULT_SCOPES)
    _outbound_tokens[tenant_id] = token
    return token


async def _get_token(
    session: AsyncSession, tenant_id: uuid.UUID, token_id: uuid.UUID
) -> TenantServiceToken:
    row = (
        await session.execute(
            select(TenantServiceToken).where(
                TenantServiceToken.tenant_id == tenant_id,
                TenantServiceToken.id == token_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("service token not found")
    return row
