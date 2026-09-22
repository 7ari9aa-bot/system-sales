"""Per-tenant n8n service tokens (§136) — issue / verify / rotate / revoke.

These replace the single global SERVICE_TOKEN_INTERNAL Bearer: a token
issued to tenant A must be worthless under tenant B, the plaintext must
never be stored, and rotation must kill the predecessor.

DB-backed: runs against a real PostgreSQL as the `sales_app` role with RLS
enforced (see conftest); skips when no app database URL is configured.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import select

from app.core.db import bind_tenant
from app.core.errors import PermissionDeniedError
from app.modules.automation.tokens import (
    get_or_issue_outbound_token,
    issue_token,
    revoke_token,
    rotate_token,
    verify_token,
)
from app.modules.identity.models import Tenant
from app.modules.platform.models import OutboxEvent, TenantServiceToken

SCOPES = ["automation:callback", "automation:trigger"]


async def test_issue_returns_plaintext_once_and_stores_only_the_hash(db, tenant_ctx):
    token = await issue_token(db, tenant_ctx.tenant_id, "ci-test", SCOPES)

    assert token.startswith("tst_")
    row = (
        await db.execute(
            select(TenantServiceToken).where(
                TenantServiceToken.tenant_id == tenant_ctx.tenant_id
            )
        )
    ).scalar_one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    # the plaintext itself is never persisted — only its digest
    assert token not in row.token_hash
    assert row.scopes == SCOPES
    assert row.revoked_at is None


async def test_issue_stages_an_outbox_event(db, tenant_ctx):
    token = await issue_token(db, tenant_ctx.tenant_id, "ci-outbox", SCOPES)
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = (
        await db.execute(
            select(TenantServiceToken).where(TenantServiceToken.token_hash == digest)
        )
    ).scalar_one()

    event = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_type == "tenant_service_token",
                OutboxEvent.aggregate_id == row.id,
            )
        )
    ).scalar_one()
    assert event.payload["event_type"] == "automation.service_token.issued"


async def test_verify_accepts_the_correct_token(db, tenant_ctx):
    token = await issue_token(db, tenant_ctx.tenant_id, "ci-verify", SCOPES)

    verified = await verify_token(
        db,
        token,
        tenant_id=tenant_ctx.tenant_id,
        required_scope="automation:callback",
    )

    assert verified.tenant_id == tenant_ctx.tenant_id
    assert verified.last_used_at is not None


async def test_verify_rejects_a_wrong_token(db, tenant_ctx):
    await issue_token(db, tenant_ctx.tenant_id, "ci-wrong", SCOPES)

    with pytest.raises(PermissionDeniedError):
        await verify_token(db, "tst_not-the-issued-token", tenant_id=tenant_ctx.tenant_id)


async def test_verify_rejects_a_revoked_token(db, tenant_ctx):
    token = await issue_token(db, tenant_ctx.tenant_id, "ci-revoke", SCOPES)
    verified = await verify_token(db, token, tenant_id=tenant_ctx.tenant_id)

    await revoke_token(db, tenant_ctx.tenant_id, verified.id)

    with pytest.raises(PermissionDeniedError):
        await verify_token(db, token, tenant_id=tenant_ctx.tenant_id)


async def test_verify_rejects_a_missing_scope(db, tenant_ctx):
    token = await issue_token(db, tenant_ctx.tenant_id, "ci-scope", ["automation:trigger"])

    with pytest.raises(PermissionDeniedError):
        await verify_token(
            db,
            token,
            tenant_id=tenant_ctx.tenant_id,
            required_scope="automation:callback",
        )


async def test_a_token_cannot_be_verified_under_another_tenant(db, tenant_ctx):
    """A's token reads as nonexistent under B (FORCE RLS) — and the explicit
    tenant check would reject it even for an unbound caller."""
    token = await issue_token(db, tenant_ctx.tenant_id, "ci-tenant-a", SCOPES)

    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)

    with pytest.raises(PermissionDeniedError):
        await verify_token(db, token, tenant_id=other.id)


async def test_rotation_revokes_the_old_token(db, tenant_ctx):
    old_token = await issue_token(db, tenant_ctx.tenant_id, "ci-rotate", SCOPES)
    old_row = await verify_token(db, old_token, tenant_id=tenant_ctx.tenant_id)

    new_token = await rotate_token(db, tenant_ctx.tenant_id, old_row.id)

    with pytest.raises(PermissionDeniedError):
        await verify_token(db, old_token, tenant_id=tenant_ctx.tenant_id)
    new_row = await verify_token(db, new_token, tenant_id=tenant_ctx.tenant_id)
    assert new_row.rotated_from_id == old_row.id
    assert new_row.scopes == SCOPES


async def test_outbound_reissue_revokes_the_previous_active_token(db, tenant_ctx):
    """M4: the in-process outbound cache dies with the process but the old
    DB row does not — re-issuing after a restart must revoke the predecessor
    instead of leaving another live credential behind."""
    from app.modules.automation import tokens as tokens_module

    tokens_module._outbound_tokens.pop(tenant_ctx.tenant_id, None)
    try:
        first = await get_or_issue_outbound_token(db, tenant_ctx.tenant_id)
        # Same process: the cache answers, and NO new row appears.
        again = await get_or_issue_outbound_token(db, tenant_ctx.tenant_id)
        assert again == first

        # Simulate a restart: the cache is gone, the row is still active.
        tokens_module._outbound_tokens.pop(tenant_ctx.tenant_id, None)
        second = await get_or_issue_outbound_token(db, tenant_ctx.tenant_id)
        assert second != first

        with pytest.raises(PermissionDeniedError):
            await verify_token(db, first, tenant_id=tenant_ctx.tenant_id)
        await verify_token(db, second, tenant_id=tenant_ctx.tenant_id)

        active_outbound = (
            await db.execute(
                select(TenantServiceToken).where(
                    TenantServiceToken.tenant_id == tenant_ctx.tenant_id,
                    TenantServiceToken.name == "n8n-outbound",
                    TenantServiceToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert len(active_outbound) == 1
    finally:
        tokens_module._outbound_tokens.pop(tenant_ctx.tenant_id, None)
