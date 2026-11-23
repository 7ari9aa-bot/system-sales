"""Instagram Login: the standalone path, with no Facebook Page in between.

Meta runs two different Instagram logins, and they are not interchangeable:

* **Facebook Login for Business** (the existing path) authorizes a Page and hands back the Page's
  ``instagram_business_account``. The credential is a PAGE token, the Graph host is
  ``graph.facebook.com``, and the scopes are the ``instagram_*`` family that rides a Page token.
* **Instagram Login** (this module) authorizes the Instagram professional account itself. The
  credential is an INSTAGRAM token, the Graph host is ``graph.instagram.com``, and the scopes are
  the ``instagram_business_*`` family. It needs no Page at all, which is the whole point: an
  account that is not linked to a Page can connect.

Nothing here is guessed: the authorize host, the token host, the long-lived exchange and the
``instagram_business_*`` scope names are Meta's documented Instagram Login endpoints
(developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ExternalProviderError, ValidationError
from app.core.secrets import encrypt_credentials_dict
from app.modules.platform.models import Integration

logger = logging.getLogger(__name__)

#: Instagram Login scopes. Deliberately NOT one ``pages_*`` scope: this grant never touches a Page,
#: and asking for a Page permission here would make Meta reject the whole dialog.
INSTAGRAM_LOGIN_SCOPES = (
    "instagram_business_basic,"
    "instagram_business_manage_messages,"
    "instagram_business_manage_comments,"
    "instagram_business_content_publish,"
    "instagram_manage_insights"
)

#: The marker that tells the gateway which Graph host this credential belongs to.
LOGIN_MARKER = "instagram"

_AUTHORIZE = "https://www.instagram.com/oauth/authorize"
_TOKEN = "https://api.instagram.com/oauth/access_token"
_GRAPH = "https://graph.instagram.com"


def authorize_url(*, app_id: str, redirect_uri: str, state: str) -> str:
    """Instagram's own authorize URL. A different host and a different scope family."""
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": INSTAGRAM_LOGIN_SCOPES,
        "state": state,
    }
    return f"{_AUTHORIZE}?{urlencode(params)}"


def _error_of(payload: dict) -> str | None:
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("type") or "error")
    if isinstance(err, str) and err:
        return err
    if payload.get("error_message"):
        return str(payload["error_message"])
    return None


async def _json(http: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict[str, Any]:
    resp = await http.request(method, url, **kwargs)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ExternalProviderError(f"instagram_login: not JSON ({resp.status_code})") from exc
    if not isinstance(payload, dict):
        raise ExternalProviderError("instagram_login: unexpected payload")
    message = _error_of(payload)
    if resp.status_code >= 500 or resp.status_code == 429:
        raise ExternalProviderError(f"instagram_login: {resp.status_code} {message or ''}".strip())
    if resp.status_code >= 400 or message:
        # A refusal is a real answer from Meta: carry its wording, do not invent one.
        raise ValidationError(f"إنستجرام رفض تسجيل الدخول: {message or resp.status_code}")
    return payload


async def exchange_code(
    http: httpx.AsyncClient, *, app_id: str, app_secret: str, redirect_uri: str, code: str
) -> dict[str, Any]:
    """Code → short-lived token → long-lived token → the account it belongs to.

    The long-lived exchange is what makes the connection survive past an hour; a short-lived
    token would die before the owner finished testing the channel.
    """
    first = await _json(
        http,
        "POST",
        _TOKEN,
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    short_token = str(first.get("access_token") or "")
    user_id = str(first.get("user_id") or "")
    if not short_token or not user_id:
        raise ValidationError("إنستجرام لم يرجّع توكن أو معرّف حساب.")

    long_payload = await _json(
        http,
        "GET",
        f"{_GRAPH}/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        },
    )
    long_token = str(long_payload.get("access_token") or short_token)
    expires_in = long_payload.get("expires_in")

    profile = await _json(
        http,
        "GET",
        f"{_GRAPH}/me",
        params={
            "fields": "user_id,username,account_type,profile_picture_url,name",
            "access_token": long_token,
        },
    )
    return {
        "access_token": long_token,
        "expires_in": expires_in,
        "user_id": str(profile.get("user_id") or user_id),
        "username": str(profile.get("username") or ""),
        "account_type": str(profile.get("account_type") or ""),
        "name": str(profile.get("name") or ""),
        "picture": str(profile.get("profile_picture_url") or ""),
    }


async def exchange_and_connect(
    session: AsyncSession,
    http: httpx.AsyncClient,
    *,
    code: str,
    tenant_id: uuid.UUID,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
) -> tuple[str, str]:
    """Store the Instagram account as the channel. Returns (provider, display name)."""
    from app.modules.billing.service import EntitlementService
    from app.modules.customers.routers.integrations import _activate_verified_channel

    account = await exchange_code(
        http, app_id=app_id, app_secret=app_secret, redirect_uri=redirect_uri, code=code
    )
    # Instagram Login only serves professional accounts. Saying so is better than storing a
    # personal account that will fail on the first send.
    if account["account_type"].upper() not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
        raise ValidationError(
            "الحساب ده مش حساب احترافي على إنستجرام. حوّله لحساب Business أو Creator من إعدادات "
            "إنستجرام، وبعدها اربطه من هنا."
        )

    provider = "instagram"
    existing = (
        await session.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.provider == provider,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == "disabled":
        raise ValidationError("This channel was permanently disabled and cannot be reconnected.")
    if existing is None:
        await EntitlementService.ensure_channel_allowed(session, tenant_id, provider)

    config = {
        "account_id": account["user_id"],
        "username": account["username"],
        # The gateway reads this to pick graph.instagram.com instead of graph.facebook.com.
        "login": LOGIN_MARKER,
    }
    credentials = {
        "api_key": account["access_token"],
        "account_id": account["user_id"],
        # No page_access_token and no _meta.page_id: this connection has no Page, and pretending
        # otherwise would make the Page flows act on an id that does not exist.
        "login": LOGIN_MARKER,
        "_meta": {
            "expires_at": account["expires_in"],
            "refreshable": True,
            "login": LOGIN_MARKER,
        },
    }
    # Scopes are NOT recorded as "granted": Instagram Login offers no debug_token to measure
    # them, so the diagnostics report them as unverified instead of assuming them.
    connection_meta = {
        "verified_at": datetime.now(UTC).isoformat(),
        "display_name": account["username"] or account["name"] or account["user_id"],
        "login": LOGIN_MARKER,
    }
    integration_config = {**config, "_connection": connection_meta}
    encrypted = encrypt_credentials_dict(credentials)
    try:
        if existing is None:
            integration = Integration(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                provider=provider,
                kind="channel",
                config=integration_config,
                credentials=encrypted,
                status="pending",
            )
            _activate_verified_channel(integration)
            session.add(integration)
        else:
            _activate_verified_channel(existing)
            existing.config = integration_config
            existing.credentials = encrypted
            integration = existing
        await session.flush()
    except DomainError:
        raise
    except Exception as exc:  # a unique-index clash means another workspace owns this account
        logger.warning("instagram_login.save_failed error=%s", type(exc).__name__)
        raise ValidationError(
            "الحساب ده مربوط بمكان تاني بالفعل. افصل الربط القديم الأول."
        ) from exc

    display = account["username"] or account["name"] or account["user_id"]
    logger.info("instagram_login.connected tenant=%s account=%s", tenant_id, account["user_id"])
    return provider, display
