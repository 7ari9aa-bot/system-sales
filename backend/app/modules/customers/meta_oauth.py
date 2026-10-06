"""Facebook Login for Business — the Meta OAuth connect flow (spec: channels).

The operator clicks connect in the dashboard; the backend mints a short-lived
signed state and hands back Meta's authorize URL. Meta redirects the browser
to the callback with the code; the code swaps for a user token, /me/accounts
yields the messaging-capable page (and its PAGE token), the integration is
verified + persisted through the same path /integrations/connect uses, and
the page is subscribed to this app's webhooks. Every outcome lands back on
the settings page with an explicit marker — never a bare error page.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ValidationError
from app.core.secrets import encrypt_credentials_dict
from app.core.security import create_oauth_state_token, decode_token
from app.modules.identity.deps import DbSession, TenantContext, require_permission
from app.modules.platform.integration_verifier import verify_channel_credentials
from app.modules.platform.models import Integration

meta_oauth_router = APIRouter()

#: Scopes the operator grants on the Meta dialog. Messaging requires the
#: page-scoped token that /me/accounts returns for an authorized page.
_META_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_messaging,"
    "instagram_basic,instagram_messaging"
)
_META_PROVIDERS = ("messenger", "instagram")
_META_STATE_TTL_SECONDS = 600
_GRAPH = "https://graph.facebook.com/v26.0"


def _meta_config() -> tuple[str, str, str]:
    from app.core.config import get_settings

    s = get_settings()
    app_id = s.meta_app_id.strip()
    app_secret = s.meta_app_secret.strip()
    redirect_uri = s.meta_oauth_redirect_uri.strip()
    if not (app_id and app_secret and redirect_uri):
        raise ValidationError(
            "Meta OAuth is not configured on this server "
            "(META_APP_ID, META_APP_SECRET, META_OAUTH_REDIRECT_URI)."
        )
    return app_id, app_secret, redirect_uri


@meta_oauth_router.get("/integrations/meta/oauth/start")
async def meta_oauth_start(
    provider: str,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Mint a short-lived signed state and hand back the Meta authorize URL.

    The FRONTEND navigates to the returned URL — the dialog page belongs to
    Meta, and the state JWT (10 minutes, signed with the server's secret) is
    what authorizes the unauthenticated callback. The operator held
    settings:write when the URL was minted; the callback re-checks nothing
    else because the window is shorter than a coffee.
    """
    if provider not in _META_PROVIDERS:
        raise ValidationError(f"Meta OAuth covers {' and '.join(_META_PROVIDERS)} only.")
    app_id, _secret, redirect_uri = _meta_config()
    state = create_oauth_state_token(
        str(ctx.user.id),
        {"tenant_id": str(ctx.tenant_id), "provider": provider},
        ttl_seconds=_META_STATE_TTL_SECONDS,
    )
    authorize_url = (
        f"https://www.facebook.com/v26.0/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={urlencode({'uri': redirect_uri})[4:]}"
        f"&state={state}"
        f"&scope={_META_SCOPES}&response_type=code"
    )
    return {"authorize_url": authorize_url}


async def _meta_exchange_and_connect(
    session: AsyncSession, code: str, state_payload: dict
) -> tuple[str, str]:
    """code → user token → /me/accounts → connect the first messaging page.

    Returns (provider, page_name); raises on every failure so the callback
    redirects the browser with meta_error instead of a bare 500.
    """
    import httpx

    from app.core.db import bind_tenant
    from app.modules.billing.service import EntitlementService
    from app.modules.customers.router import (
        _activate_verified_channel,
        _verification_metadata,
    )

    provider = state_payload["provider"]
    tenant_id = uuid.UUID(state_payload["tenant_id"])
    app_id, app_secret, redirect_uri = _meta_config()

    await bind_tenant(session, tenant_id)
    # ONE live client for the whole flow: the ownership verification reuses
    # the exchange's client — closing it before the verify call raised
    # "client has been closed". The persist runs inside the same block so
    # the failed-open states can never outlive the connection either.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
    ) as http:
        swap = (
            await http.get(
                f"{_GRAPH}/oauth/access_token",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
        ).json()
        user_token = swap.get("access_token")
        if not user_token:
            raise ValidationError("Meta rejected the authorization code.")
        accounts = (
            await http.get(
                f"{_GRAPH}/me/accounts",
                params={
                    "fields": "id,name,access_token,tasks",
                    "access_token": user_token,
                },
            )
        ).json()

        pages = [
            page
            for page in accounts.get("data", [])
            if "MESSAGING" in (page.get("tasks") or [])
        ]
        if not pages:
            raise ValidationError("No messaging-capable page was authorized.")
        page = pages[0]

        credentials = {"api_key": page["access_token"]}
        config = {"account_id": str(page["id"])}
        verified = await verify_channel_credentials(
            provider, credentials, config, client=http
        )

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
            raise ValidationError(
                "This channel was permanently disabled and cannot be reconnected."
            )
        if existing is None:
            await EntitlementService.ensure_channel_allowed(session, tenant_id, provider)

        verified_at = datetime.now(UTC).isoformat()
        integration_config = {
            **verified.identity_config,
            "_connection": _verification_metadata(
                verified_at=verified_at, display_name=verified.display_name
            ),
        }
        encrypted = encrypt_credentials_dict(credentials)
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

        # The page-level webhook subscription: Meta delivers per PAGE, not
        # per app — the same fields the manual subscription flow selects.
        await http.post(
            f"{_GRAPH}/{page['id']}/subscribed_apps",
            params={
                "subscribed_fields": (
                    "messages,messaging_postbacks,messaging_referrals,"
                    "message_deliveries"
                ),
                "access_token": page["access_token"],
            },
        )
        return provider, str(page.get("name") or page["id"])


@meta_oauth_router.get("/integrations/meta/oauth/callback", include_in_schema=False)
async def meta_oauth_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
):
    """Meta redirects the operator's browser here with the authorization code.

    PUBLIC by design: the state JWT (10-minute TTL, server-signed) is the
    authorization — it was minted to a settings:write holder at start time.
    Every outcome lands back on the settings page with an explicit marker."""
    from fastapi.responses import RedirectResponse

    from app.core.config import get_settings
    from app.core.db import bind_tenant

    frontend = get_settings().frontend_public_url.rstrip("/")
    target = f"{frontend}/settings/channels"

    def _back(marker: str, value: str):
        return RedirectResponse(
            f"{target}?meta_{marker}={urlencode({'v': value})[2:]}", status_code=302
        )

    if not code or not state:
        return _back("error", "missing_code_or_state")
    try:
        payload = decode_token(state)
    except Exception:
        return _back("error", "invalid_state")
    if payload.get("type") != "oauth_state":
        return _back("error", "invalid_state")
    provider = payload.get("provider")
    if provider not in _META_PROVIDERS:
        return _back("error", "invalid_provider")

    try:
        await bind_tenant(session, uuid.UUID(str(payload["tenant_id"])))
        connected_provider, page_name = await _meta_exchange_and_connect(
            session, code, payload
        )
    except DomainError as exc:
        await session.rollback()
        return _back("error", f"{provider}:{str(exc)[:120]}")
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception("meta_oauth.connect_failed provider=%s", provider)
        await session.rollback()
        return _back("error", f"meta_exchange_failed:{type(exc).__name__}")

    return _back("connected", f"{connected_provider}:{page_name}")

