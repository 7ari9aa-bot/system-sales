"""Facebook Login for Business — the Meta OAuth connect flow (spec: channels).

The operator clicks connect in the dashboard; the backend mints a short-lived
signed state and hands back Meta's authorize URL (the documented manual login
dialog: developers.facebook.com/docs/facebook-login/guides/advanced/
manual-flow). Meta redirects the browser to the callback with the code; the
code swaps for a user token, the token is exchanged for a LONG-LIVED one
(the /me/accounts page tokens of a short-lived user token die after ~1 hour —
developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived),
/me/accounts yields the messaging-capable page (and its PAGE token), the
integration is verified + persisted through the same path /integrations/connect
uses, and the page is subscribed to this app's webhooks. Every outcome lands
back on the settings page with an explicit marker — never a bare error page.
"""

from __future__ import annotations

import logging
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

_logger = logging.getLogger(__name__)

#: One version pinned for BOTH the login dialog and the Graph calls — the
#: dialog URL and the API MUST match what the app's configuration expects
#: (current version per developers.facebook.com/docs/graph-api/changelog).
_META_VERSION = "v26.0"
_GRAPH = f"https://graph.facebook.com/{_META_VERSION}"

#: Scopes the operator grants on the Meta dialog, per channel provider.
#: Page messaging needs the page-scoped token /me/accounts returns for an
#: authorized page; Instagram DMs need instagram_manage_messages + the
#: linked IG business account (developers.facebook.com/docs/permissions —
#: there is NO `instagram_messaging` permission; requesting one that does
#: not exist makes Meta reject the whole dialog).
_MESSENGER_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging"
)
_INSTAGRAM_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging,"
    "instagram_basic,instagram_manage_messages"
)
_META_PROVIDERS = ("messenger", "instagram")
_META_STATE_TTL_SECONDS = 600

#: The page fields the flow consumes: tasks gates the MESSAGING capability,
#: instagram_business_account carries the IG id the Instagram gateway sends
#: against (/{ig-account-id}/messages) and the webhook routes by.
_PAGE_FIELDS = (
    "id,name,access_token,tasks,instagram_business_account{id,username}"
)


def _meta_config() -> tuple[str, str, str, str]:
    """(app_id, app_secret, redirect_uri, config_id) or a loud failure.

    redirect_uri comes from META_OAUTH_REDIRECT_URI, or is DERIVED from
    API_PUBLIC_BASE_URL (config.meta_oauth_redirect_uri_effective) — a
    deployment only needs its canonical public base URL. Empty pieces mean
    the operator forgot configuration, which must fail here, at the start
    of the flow, not at the callback with Meta's cryptic redirect error.
    """
    from app.core.config import get_settings

    s = get_settings()
    app_id = s.meta_app_id.strip()
    app_secret = s.meta_app_secret.strip()
    redirect_uri = s.meta_oauth_redirect_uri_effective
    config_id = s.meta_oauth_config_id.strip()
    if not (app_id and app_secret and redirect_uri):
        raise ValidationError(
            "Meta OAuth is not configured on this server — set META_APP_ID, "
            "META_APP_SECRET and either META_OAUTH_REDIRECT_URI or "
            "API_PUBLIC_BASE_URL (see docs/META_SETUP.md)."
        )
    return app_id, app_secret, redirect_uri, config_id


def _build_authorize_url(
    *, app_id: str, redirect_uri: str, state: str, provider: str, config_id: str
) -> str:
    """Meta's login dialog URL, per the manual-flow documentation.

    With a config_id (Facebook Login for Business, Business-type apps) the
    configuration id REPLACES the scope list; classic apps request the
    scope list directly. `response_type=code` is the server-side grant in
    both variants.
    """
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    if config_id:
        params["config_id"] = config_id
        # Documented requirement for the authorization-code grant with a
        # business configuration (system-user / long-lived tokens).
        params["override_default_response_type"] = "true"
    else:
        params["scope"] = (
            _MESSENGER_SCOPES if provider == "messenger" else _INSTAGRAM_SCOPES
        )
    return f"https://www.facebook.com/{_META_VERSION}/dialog/oauth?{urlencode(params)}"


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
    app_id, _secret, redirect_uri, config_id = _meta_config()
    state = create_oauth_state_token(
        str(ctx.user.id),
        {"tenant_id": str(ctx.tenant_id), "provider": provider},
        ttl_seconds=_META_STATE_TTL_SECONDS,
    )
    authorize_url = _build_authorize_url(
        app_id=app_id,
        redirect_uri=redirect_uri,
        state=state,
        provider=provider,
        config_id=config_id,
    )
    return {"authorize_url": authorize_url}


def _meta_graph_error(payload: dict, *, step: str) -> str | None:
    """Meta error message from a Graph response, if the call failed."""
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = str(error.get("message") or "").strip()
    code = error.get("code")
    return f"{step} failed ({code}): {message}" if code else f"{step} failed: {message}"


async def _meta_exchange_and_connect(
    session: AsyncSession, code: str, state_payload: dict
) -> tuple[str, str]:
    """code → user token → long-lived token → /me/accounts → connect the page.

    Returns (provider, display_name); raises on every failure so the callback
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
    app_id, app_secret, redirect_uri, _config_id = _meta_config()

    await bind_tenant(session, tenant_id)
    # ONE live client for the whole flow: the ownership verification reuses
    # the exchange's client — closing it before the verify call raised
    # "client has been closed". The persist runs inside the same block so
    # the failed-open states can never outlive the connection either.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
    ) as http:
        # 1) Authorization code → user token (server-to-server; the app
        #    secret must never see the browser).
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
        failure = _meta_graph_error(swap, step="code exchange")
        if failure:
            _logger.warning("meta_oauth.exchange_failed %s", failure)
            raise ValidationError(failure[:200])
        user_token = swap.get("access_token")
        if not user_token:
            raise ValidationError("Meta rejected the authorization code.")

        # 2) Short-lived → LONG-LIVED user token (fb_exchange_token grant).
        #    A page token minted from a short-lived user token expires in
        #    about an hour and the channel would die silently; a page token
        #    minted from a long-lived user token does not expire. Tokens
        #    that do not expire (system-user access tokens from a business
        #    config_id) carry no expires_in and skip the exchange.
        if swap.get("expires_in"):
            long_lived = (
                await http.get(
                    f"{_GRAPH}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": app_id,
                        "client_secret": app_secret,
                        "fb_exchange_token": user_token,
                    },
                )
            ).json()
            long_token = long_lived.get("access_token")
            if not long_token:
                failure = _meta_graph_error(long_lived, step="long-lived exchange")
                _logger.warning("meta_oauth.longlived_failed %s", failure)
                raise ValidationError(
                    (failure or "Meta refused the long-lived token exchange.")[:200]
                )
            user_token = long_token

        # 3) Pages the operator manages, WITH their page tokens.
        accounts = (
            await http.get(
                f"{_GRAPH}/me/accounts",
                params={"fields": _PAGE_FIELDS, "access_token": user_token},
            )
        ).json()
        failure = _meta_graph_error(accounts, step="page listing")
        if failure:
            _logger.warning("meta_oauth.accounts_failed %s", failure)
            raise ValidationError(failure[:200])

        pages = [
            page
            for page in accounts.get("data", [])
            if "MESSAGING" in (page.get("tasks") or [])
        ]
        if not pages:
            raise ValidationError("No messaging-capable page was authorized.")
        page = pages[0]

        # 4) Credentials + routing identity per gateway contract:
        #    - the webhook routes inbound by config.account_id;
        #    - the Instagram gateway SENDS against the IG business account
        #      (/{ig-id}/messages with the PAGE token), so that id must ride
        #      the encrypted credentials too.
        page_token = page["access_token"]
        config = {"account_id": str(page["id"])}
        credentials = {"api_key": page_token}
        if provider == "instagram":
            ig_account = page.get("instagram_business_account") or {}
            ig_id = str(ig_account.get("id") or "")
            if not ig_id:
                raise ValidationError(
                    "No Instagram professional account is linked to the "
                    "authorized page — link one in Meta Business Suite first."
                )
            config["account_id"] = ig_id
            credentials["account_id"] = ig_id

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
                "access_token": page_token,
            },
        )
        display_name = verified.display_name or str(page.get("name") or page["id"])
        return provider, display_name


@meta_oauth_router.get("/integrations/meta/oauth/callback", include_in_schema=False)
async def meta_oauth_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    # Typed as text on purpose: a coercion failure would 422 the PUBLIC
    # callback instead of redirecting the operator back with the reason.
    error_code: str | None = None,
):
    """Meta redirects the operator's browser here with the authorization code.

    PUBLIC by design: the state JWT (10-minute TTL, server-signed) is the
    authorization — it was minted to a settings:write holder at start time.
    Every outcome lands back on the settings page with an explicit marker;
    Meta's own dialog errors (access_denied for a cancelled consent or a
    non-tester on a dev-mode app, redirect_uri mismatches, …) are carried
    through verbatim instead of collapsing into a generic failure."""
    from fastapi.responses import RedirectResponse

    from app.core.config import get_settings
    from app.core.db import bind_tenant

    frontend = get_settings().frontend_public_url.rstrip("/")
    target = f"{frontend}/settings/channels"

    def _back(marker: str, value: str):
        return RedirectResponse(
            f"{target}?meta_{marker}={urlencode({'v': value})[2:]}", status_code=302
        )

    # Meta redirects here with error params when the DIALOG failed (the user
    # declined, the app is in dev mode and the user is not a tester, the
    # redirect_uri is not whitelisted, …). Surface Meta's own description.
    if error and not code:
        description = (error_description or "").strip() or "authorization was denied"
        detail = f"{error}:{description}"[:160]
        _logger.warning(
            "meta_oauth.dialog_error error=%s code=%s desc=%s",
            error,
            error_code,
            (error_description or "")[:200],
        )
        return _back("error", detail)

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
        _logger.exception("meta_oauth.connect_failed provider=%s", provider)
        await session.rollback()
        return _back("error", f"meta_exchange_failed:{type(exc).__name__}")

    return _back("connected", f"{connected_provider}:{page_name}")
