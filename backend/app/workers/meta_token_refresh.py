"""Refresh expiring Meta system-user credentials before they interrupt channels."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.core.meta_tokens import token_expiry
from app.platform.platform.models import Integration

logger = logging.getLogger(__name__)

_META_PROVIDERS = ("whatsapp", "facebook", "messenger", "instagram")
_REFRESH_WINDOW = timedelta(days=7)
_RETRY_AFTER = timedelta(hours=12)
_META_VERSION = "v27.0"
_GRAPH = f"https://graph.facebook.com/{_META_VERSION}"


class MetaNeedsReauthorization(ValueError):
    """Meta revoked the grant or the connected page is no longer available."""


# What Meta documents as "the grant behind this token is gone": 190 is an invalid or revoked
# token, 102 an ended session, 10 and 200 a permission the app no longer holds, 368 a block on
# the account. Retrying any of them every 12 hours only leaves a dead channel looking active.
_DEAD_GRANT_CODES = frozenset({190, 102, 10, 200, 368})


def _grant_is_dead(error: object, status_code: int) -> bool:
    code = error.get("code") if isinstance(error, dict) else None
    return code in _DEAD_GRANT_CODES or status_code in {401, 403}


def _due(credentials: dict, now: datetime) -> bool:
    metadata = credentials.get("_meta")
    if not isinstance(metadata, dict) or not metadata.get("refreshable"):
        return False
    raw_attempt = metadata.get("last_attempt_at")
    if isinstance(raw_attempt, str):
        try:
            last_attempt = datetime.fromisoformat(raw_attempt)
        except ValueError:
            last_attempt = None
        if last_attempt is not None:
            if last_attempt.tzinfo is None:
                last_attempt = last_attempt.replace(tzinfo=UTC)
            if last_attempt > now - _RETRY_AFTER:
                return False
    raw_expiry = metadata.get("expires_at")
    if not isinstance(raw_expiry, str):
        return False
    try:
        expiry = datetime.fromisoformat(raw_expiry)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= now + _REFRESH_WINDOW


async def _refresh_source_token(
    http: httpx.AsyncClient, source_token: str, *, app_id: str, app_secret: str
) -> tuple[str, str | None]:
    response = await http.get(
        f"{_GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": source_token,
            "set_token_expires_in_60_days": "true",
        },
    )
    try:
        payload = response.json()
    except ValueError:
        raise ValueError("Meta returned an invalid token refresh response") from None
    if not response.is_success or not isinstance(payload, dict) or payload.get("error"):
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        # Never log the response body; provider errors may echo credential data.
        if _grant_is_dead(error, response.status_code):
            raise MetaNeedsReauthorization("Meta rejected the stored system-user grant")
        if response.status_code == 429 or response.status_code >= 500:
            raise httpx.RequestError(
                "Meta refresh temporarily unavailable", request=response.request
            )
        raise ValueError(f"Meta token refresh failed (code={code or 'unknown'})")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("Meta returned no token during refresh")
    # Meta's refresh contract makes the resulting expiring system-user token
    # valid for 60 days; some Graph responses omit expires_in.
    expiry = token_expiry(payload.get("expires_in")) or token_expiry(60 * 24 * 60 * 60)
    return token, expiry


async def _refresh_page_token(http: httpx.AsyncClient, *, source_token: str, page_id: str) -> str:
    response = await http.get(
        f"{_GRAPH}/me/accounts",
        params={
            "fields": "id,access_token",
            "access_token": source_token,
        },
    )
    try:
        payload = response.json()
    except ValueError:
        raise ValueError("Meta returned an invalid page-token response") from None
    if not response.is_success or not isinstance(payload, dict) or payload.get("error"):
        if response.status_code == 429 or response.status_code >= 500:
            raise httpx.RequestError(
                "Meta page lookup temporarily unavailable", request=response.request
            )
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if _grant_is_dead(error, response.status_code) or response.status_code == 400:
            raise MetaNeedsReauthorization("Meta rejected the renewed page grant")
        raise ValueError("Meta refused to refresh the connected page token")
    pages = payload.get("data")
    if isinstance(pages, list):
        for page in pages:
            if isinstance(page, dict) and str(page.get("id") or "") == page_id:
                token = page.get("access_token")
                if isinstance(token, str) and token:
                    return token
    raise MetaNeedsReauthorization("Connected Facebook page is no longer accessible")


async def refresh_integration(session, integration: Integration, http: httpx.AsyncClient) -> bool:
    """Refresh a due channel credential; caller owns the transaction and tenant binding."""
    from app.core.config import get_settings
    from app.core.secrets import encrypt_credentials_dict
    from app.platform.platform.services.secrets import IntegrationCredentialsService

    credentials = await IntegrationCredentialsService.decrypt(session, integration)
    metadata = credentials.get("_meta")
    now = datetime.now(UTC)
    settings = get_settings()
    if (
        not isinstance(metadata, dict)
        and integration.provider == "whatsapp"
        and settings.meta_whatsapp_config_id.strip()
        and isinstance(credentials.get("access_token"), str)
    ):
        # Older Embedded Signup rows already hold the system-user source token,
        # but predate expiry metadata. Safely attempt one refresh to enroll them.
        metadata = {
            "refreshable": True,
            "expires_at": now.isoformat(),
            "legacy_unknown_expiry": True,
        }
        credentials["_meta"] = metadata
    if not isinstance(metadata, dict) or not _due(credentials, now):
        return False

    app_id = settings.meta_app_id.strip()
    app_secret = settings.meta_app_secret.strip()
    if not app_id or not app_secret:
        logger.error("meta_token_refresh.not_configured provider=%s", integration.provider)
        return False

    source_token = (
        credentials.get("access_token")
        if integration.provider == "whatsapp"
        else metadata.get("source_access_token")
    )
    if not isinstance(source_token, str) or not source_token:
        logger.error("meta_token_refresh.missing_source provider=%s", integration.provider)
        return False

    try:
        metadata["last_attempt_at"] = now.isoformat()
        new_token, expiry = await _refresh_source_token(
            http, source_token, app_id=app_id, app_secret=app_secret
        )
        if integration.provider == "whatsapp":
            credentials["access_token"] = new_token
        else:
            page_id = metadata.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                raise ValueError("Meta page identity is missing")
            page_token = await _refresh_page_token(http, source_token=new_token, page_id=page_id)
            if integration.provider == "facebook":
                credentials["page_access_token"] = page_token
            else:
                credentials["api_key"] = page_token
            metadata["source_access_token"] = new_token
        metadata["expires_at"] = expiry
        credentials["_meta"] = metadata
        integration.credentials = encrypt_credentials_dict(credentials)
        await session.flush()
        logger.info("meta_token_refresh.succeeded provider=%s", integration.provider)
        return True
    except MetaNeedsReauthorization:
        credentials["_meta"] = metadata
        integration.credentials = encrypt_credentials_dict(credentials)
        if integration.status == "active":
            Integration.validate_transition("active", "reauth_required")
            integration.status = "reauth_required"
        from app.platform.platform.services.audit import AuditService

        await AuditService.write(
            session,
            integration.tenant_id,
            None,
            "integration.token_refresh_failed",
            "integration",
            str(integration.id),
            before={"status": "active"},
            after={"status": integration.status, "reason": "reauthorization_required"},
        )
        await session.flush()
        logger.warning(
            "meta_token_refresh.reauthorization_required provider=%s", integration.provider
        )
        return False
    except (httpx.RequestError, ValueError) as exc:
        if metadata.get("legacy_unknown_expiry") and isinstance(exc, ValueError):
            # A legacy, unexpired permanent token may not support the refresh
            # grant. Stop probing it; only explicit OAuth invalidation above
            # should force an owner back through signup.
            metadata["refreshable"] = False
            metadata["refresh_status"] = "unsupported_legacy_token"
        credentials["_meta"] = metadata
        integration.credentials = encrypt_credentials_dict(credentials)
        await session.flush()
        logger.warning(
            "meta_token_refresh.failed provider=%s",
            integration.provider,
        )
        return False


async def sweep_expiring_tokens() -> int:
    """Cross-tenant scheduled sweep, with one RLS-bound transaction per tenant."""
    from app.platform.identity.models import Tenant

    async with SessionLocal() as session:
        tenant_ids = (
            (await session.execute(select(Tenant.id).where(Tenant.is_active))).scalars().all()
        )

    refreshed = 0
    for tenant_id in tenant_ids:
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                rows = (
                    (
                        await session.execute(
                            select(Integration)
                            .where(
                                Integration.tenant_id == tenant_id,
                                Integration.provider.in_(_META_PROVIDERS),
                                Integration.kind == "channel",
                                Integration.status == "active",
                            )
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .scalars()
                    .all()
                )
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False
                ) as http:
                    for integration in rows:
                        if await refresh_integration(session, integration, http):
                            refreshed += 1
    return refreshed
