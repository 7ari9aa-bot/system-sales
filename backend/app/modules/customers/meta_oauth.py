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

import asyncio
import json
import logging
import secrets as py_secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ExternalProviderError, ValidationError
from app.core.redis import get_redis
from app.core.secrets import decrypt_credentials_dict, encrypt_credentials_dict
from app.core.security import create_oauth_state_token, decode_token
from app.modules.customers.meta_scopes import (
    FACEBOOK_SCOPES,
    MESSENGER_SCOPES,
    granted_scopes_from_permissions,
    missing_facebook_scopes,
)
from app.modules.customers.schemas import MetaOAuthChoosePageOut, MetaOAuthStartOut
from app.modules.identity.deps import DbSession, TenantContext, require_permission
from app.modules.platform.integration_verifier import verify_channel_credentials
from app.modules.platform.models import Integration

meta_oauth_router = APIRouter()

_logger = logging.getLogger(__name__)

#: One version pinned for BOTH the login dialog and the Graph calls — the
#: dialog URL and the API MUST match what the app's configuration expects
#: (current version per developers.facebook.com/docs/graph-api/changelog).
_META_VERSION = "v27.0"
_GRAPH = f"https://graph.facebook.com/{_META_VERSION}"

#: Scopes the operator grants on the Meta dialog, per channel provider.
#: Page messaging needs the page-scoped token /me/accounts returns for an
#: authorized page; Instagram DMs need instagram_manage_messages + the
#: linked IG business account (developers.facebook.com/docs/permissions —
#: there is NO `instagram_messaging` permission; requesting one that does
#: not exist makes Meta reject the whole dialog).
_MESSENGER_SCOPES = MESSENGER_SCOPES
_INSTAGRAM_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging,"
    "instagram_basic,instagram_manage_messages,"
    # Posts and comments from the inbox: read and moderate comments, answer one in
    # private, and publish a post. A store connected before this must reconnect once
    # to grant them; the DM scopes above are unchanged, so existing chats keep working.
    "instagram_manage_comments,instagram_content_publish"
)
# Webhook fields the PAGE subscription asks for, per channel. Only fields that exist on Meta's
# `page` object are listed. Instagram's own fields (comments, mentions, message_reactions,
# messaging_seen, live_comments) are NOT Page fields: Meta states that `subscribed_fields` on
# /{page_id}/subscribed_apps does not configure Instagram webhooks. They are subscribed on the
# `instagram` object in the App Dashboard (callback /webhooks/instagram, see docs/META_SETUP.md).
# An Instagram connection still needs its linked Page subscribed, with the chat fields below.
_BASE_SUBSCRIBED_FIELDS = (
    "messages,messaging_postbacks,messaging_referrals,message_deliveries,message_reads"
)
# A customer's emoji reaction to a Messenger message arrives on the Page's `message_reactions`
# field. It is a Page field for Messenger and Facebook connections only: on Instagram the same
# name belongs to the `instagram` object, so it stays out of `_BASE_SUBSCRIBED_FIELDS` (a Page
# subscription naming it for an Instagram link is ignored or rejected).
_MESSENGER_SUBSCRIBED_FIELDS = _BASE_SUBSCRIBED_FIELDS + ",message_reactions"
_SUBSCRIBED_FIELDS = {
    "messenger": _MESSENGER_SUBSCRIBED_FIELDS,
    "instagram": _BASE_SUBSCRIBED_FIELDS,
    # Facebook Page comments are delivered on the Page's `feed` field; without it a
    # connected Page only ever gets its Messenger traffic. `mention` is the Page tagged
    # in someone else's post or comment.
    "facebook": _MESSENGER_SUBSCRIBED_FIELDS + ",feed,mention",
}


def subscribed_fields(provider: str) -> str:
    return _SUBSCRIBED_FIELDS.get(provider, _MESSENGER_SUBSCRIBED_FIELDS)


# A Facebook connection is the same page-messaging grant as Messenger — the
# page-scoped token IS the credential; the provider value only names the row.
_META_PROVIDERS = ("messenger", "instagram", "facebook")
#: 15 minutes, deliberately LONGER than the 10 the settings screen waits. The state is minted
#: before the screen starts its own clock, so with equal windows an owner finishing in the last
#: seconds met an expired state while the screen was still waiting. The screen is the one that
#: gives up first and says so; the server only has to still be listening.
_META_STATE_TTL_SECONDS = 900

#: The page fields the flow consumes: tasks gates the MESSAGING capability,
#: instagram_business_account carries the IG id the Instagram gateway sends
#: against (/{ig-account-id}/messages) and the webhook routes by.
_PAGE_FIELDS = "id,name,access_token,tasks,instagram_business_account{id,username}"


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
    config_id = s.meta_instagram_config_id.strip()
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

    With a config_id (Facebook Login for Business) the configuration id
    REPLACES the scope list; without one the scope list is requested
    directly. Only Instagram has a configuration of its own, so the id is
    ignored for Facebook and Messenger: one configuration must never narrow
    another channel's permissions. `response_type=code` is the server-side
    grant in both variants.
    """
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    if config_id and provider == "instagram":
        params["config_id"] = config_id
        # Documented requirement for the authorization-code grant with a
        # business configuration (system-user / long-lived tokens).
        params["override_default_response_type"] = "true"
    else:
        if provider == "instagram":
            params["scope"] = _INSTAGRAM_SCOPES
        elif provider == "facebook":
            params["scope"] = FACEBOOK_SCOPES
        else:  # messenger: the page-messaging grant only
            params["scope"] = _MESSENGER_SCOPES
    return f"https://www.facebook.com/{_META_VERSION}/dialog/oauth?{urlencode(params)}"


@meta_oauth_router.get("/integrations/meta/oauth/start", response_model=MetaOAuthStartOut)
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


def _graph_json(response: httpx.Response, *, step: str) -> dict:
    """The JSON body of a Graph response, or a retryable outage.

    A 429, a 5xx, or a body that is not a JSON object (a gateway's HTML page, a captive portal)
    means Meta, or the path to it, is unavailable. That is NOT a configuration mistake, so it must
    never reach the owner as one. A 4xx that carries Meta's own ``error`` object is returned as is:
    the caller names Meta's explanation.
    """
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(f"Meta is temporarily unavailable ({step}).", retryable=True)
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError(
            f"Meta returned an unreadable response ({step}).", retryable=True
        ) from None
    if not isinstance(payload, dict):
        raise ExternalProviderError(
            f"Meta returned an unexpected response ({step}).", retryable=True
        )
    return payload


def _meta_graph_error(payload: dict, *, step: str) -> str | None:
    """Meta error message from a Graph response, if the call failed."""
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = str(error.get("message") or "").strip()
    code = error.get("code")
    return f"{step} failed ({code}): {message}" if code else f"{step} failed: {message}"


async def _flag(
    key: str, provider: str | None, tenant_id: uuid.UUID | None, details: dict | None = None
) -> None:
    """Name a linking failure on the channel's trail. Never raises, never changes the outcome."""
    from app.core.meta_diagnostics import record_channel_issue

    await record_channel_issue(key, channel=provider, tenant_id=tenant_id, details=details)


def _graph_fields(payload: dict) -> dict:
    """Meta's own error fields (code, subcode, type, fbtrace_id) for a failed Graph response."""
    from app.core.meta_diagnostics import graph_error_fields

    return graph_error_fields(payload.get("error") if isinstance(payload, dict) else None)


async def _existing_subscribed_fields(http, *, page_id: str, page_token: str) -> list[str]:
    """The webhook fields this app already has on the Page, or [] when they cannot be read."""
    try:
        response = await http.get(
            f"{_GRAPH}/{page_id}/subscribed_apps", params={"access_token": page_token}
        )
        if not response.is_success:
            return []
        data = response.json().get("data")
    except (httpx.RequestError, ValueError, AttributeError):
        return []
    fields: list[str] = []
    for entry in data if isinstance(data, list) else []:
        raw = entry.get("subscribed_fields") if isinstance(entry, dict) else None
        fields.extend(f for f in (raw if isinstance(raw, list) else []) if isinstance(f, str) and f)
    return fields


async def _subscribe_page_to_app(
    http, *, page_id: str, page_token: str, provider: str = "messenger"
) -> None:
    """Fail the connection if the page cannot receive this app's webhooks.

    The fields are the channel's own: a Facebook Page also needs `feed` for its comments and
    an Instagram account `comments`, which the base messaging fields alone never deliver."""
    wanted = subscribed_fields(provider)
    # Meta REPLACES the list on every POST. A Page that Facebook already linked for its
    # comments (`feed`) would lose them the moment Messenger is linked on it, with no error.
    # So keep what is already there. Reading it is a courtesy: if it fails, the channel's own
    # fields are still written, exactly as before.
    kept = await _existing_subscribed_fields(http, page_id=page_id, page_token=page_token)
    merged = list(dict.fromkeys([*wanted.split(","), *kept]))
    try:
        response = await http.post(
            f"{_GRAPH}/{page_id}/subscribed_apps",
            params={
                "subscribed_fields": ",".join(merged),
                "access_token": page_token,
            },
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not configure the Meta page webhook subscription. Try again."
        ) from None
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(
            "Meta is temporarily unavailable while configuring page webhooks.", retryable=True
        )
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError("Meta returned an invalid page webhook response.") from None
    if response.is_error or not isinstance(payload, dict) or payload.get("success") is not True:
        raise ExternalProviderError(
            "Meta refused the page webhook subscription. Check the app's messaging permissions."
        )


class PageChoiceRequired(Exception):
    """The owner ticked several Pages: the connect pauses until they pick one.

    Carries the parked ticket and the choices (id and name only — never a token)."""

    def __init__(self, ticket: str, choices: list[dict]) -> None:
        super().__init__("page_choice_required")
        self.ticket = ticket
        self.choices = choices


#: How long the owner has to pick a Page. The same window as the state token's, margin included.
_PAGE_CHOICE_TTL_SECONDS = _META_STATE_TTL_SECONDS


def _page_choice_key(ticket: str) -> str:
    return f"meta_oauth:page_choice:{ticket}"


async def _business_portfolio_pages(http, user_token: str) -> list[dict]:
    """Pages owned by (or shared with) the operator's Business Portfolios, WITH page tokens.

    /me/accounts omits Pages that live inside a Business Portfolio. Meta lists them under
    /me/businesses → /{business}/owned_pages and /client_pages, and each entry can carry its own
    page access_token when the operator has a task on it. Best effort: any failure returns [].
    """
    found: dict[str, dict] = {}
    try:
        biz = _graph_json(
            await http.get(
                f"{_GRAPH}/me/businesses",
                params={"fields": "id,name", "limit": 50, "access_token": user_token},
            ),
            step="business listing",
        )
        _logger.info(
            "meta_oauth.business_listing businesses=%s error=%s",
            len(biz.get("data", []) if isinstance(biz, dict) else []),
            _graph_fields(biz) if isinstance(biz, dict) else None,
        )
        for business in biz.get("data", []) if isinstance(biz, dict) else []:
            for edge in ("owned_pages", "client_pages"):
                listing = _graph_json(
                    await http.get(
                        f"{_GRAPH}/{business['id']}/{edge}",
                        params={
                            "fields": _PAGE_FIELDS,
                            "limit": 100,
                            "access_token": user_token,
                        },
                    ),
                    step=f"business {edge}",
                )
                for page in listing.get("data", []) if isinstance(listing, dict) else []:
                    if page.get("id") and page.get("access_token"):
                        found[str(page["id"])] = page
    except Exception as exc:  # noqa: BLE001 - diagnostic fallback must never break the connect
        _logger.warning("meta_oauth.business_pages_failed %s", str(exc)[:200])
    return list(found.values())


async def _granted_target_pages(http, user_token: str) -> list[dict]:
    """Pages the owner ticked on the dialog, found through the token's own grant, WITH tokens.

    /me/accounts omits a Page that lives in a Business Portfolio, and /me/businesses needs
    business_management, which the app does not ask for. Meta still records the exact assets the
    owner picked in the token's granular scopes (`/debug_token`, `target_ids`), and a Page's own
    node returns its page access_token to a user who holds a task on it. So read the ids from the
    grant and fetch each Page directly. Best effort: any failure returns [].
    """
    from app.core.config import get_settings

    s = get_settings()
    app_token = f"{s.meta_app_id.strip()}|{s.meta_app_secret.strip()}"
    found: dict[str, dict] = {}
    try:
        debug = _graph_json(
            await http.get(
                f"{_GRAPH}/debug_token",
                params={"input_token": user_token, "access_token": app_token},
            ),
            step="token debug",
        )
        data = debug.get("data", {}) if isinstance(debug, dict) else {}
        _logger.info(
            "meta_oauth.debug_token type=%s granular=%s error=%s",
            data.get("type"),
            {
                str(sc.get("scope")): len(sc.get("target_ids") or [])
                for sc in data.get("granular_scopes") or []
            },
            _graph_fields(debug) if isinstance(debug, dict) else None,
        )
        ids: list[str] = []
        for scope in data.get("granular_scopes") or []:
            if scope.get("scope") in {
                "pages_show_list",
                "pages_messaging",
                "pages_manage_metadata",
            }:
                ids.extend(str(i) for i in scope.get("target_ids") or [])
        for page_id in dict.fromkeys(ids):
            page = _graph_json(
                await http.get(
                    f"{_GRAPH}/{page_id}",
                    params={"fields": _PAGE_FIELDS, "access_token": user_token},
                ),
                step="granted page",
            )
            _logger.info(
                "meta_oauth.granted_page id=%s has_token=%s has_ig=%s error=%s",
                page_id,
                bool(isinstance(page, dict) and page.get("access_token")),
                bool(isinstance(page, dict) and page.get("instagram_business_account")),
                _graph_fields(page) if isinstance(page, dict) else None,
            )
            if isinstance(page, dict) and page.get("id") and page.get("access_token"):
                found[str(page["id"])] = page
    except Exception as exc:  # noqa: BLE001 - diagnostic fallback must never break the connect
        _logger.warning("meta_oauth.granted_pages_failed %s", str(exc)[:200])
    return list(found.values())


def _messaging_pages(all_pages: list[dict]) -> list[dict]:
    """The Pages this operator can run messaging on.

    A Page whose `tasks` list is missing or empty is kept (older Graph answers omit it). A Page
    whose list is present but names neither MESSAGING nor MANAGE is NOT one the operator can run
    chat on, so it is never offered, not even as a fallback when nothing else qualifies: the old
    fallback returned every Page and let the owner connect one Meta would then refuse.
    """
    return [
        page
        for page in all_pages
        if not page.get("tasks")
        or "MESSAGING" in (page.get("tasks") or [])
        or "MANAGE" in (page.get("tasks") or [])
    ]


def _page_choices(pages: list[dict]) -> list[dict]:
    """What the browser may see about a Page: its id and name, nothing secret."""
    return [{"id": str(page["id"]), "name": str(page.get("name") or page["id"])} for page in pages]


async def _park_page_choice(
    *,
    tenant_id: uuid.UUID,
    user_id: str,
    provider: str,
    user_token: str,
    expires_in,
    granted,
    config_id: str,
    page_ids: list[str],
) -> str:
    """Keep the long-lived user token server-side, encrypted, while the owner picks a Page.

    Only an opaque one-time ticket goes to the browser. The Page tokens are not stored at all:
    they are listed again from the user token when the choice comes back."""
    ticket = py_secrets.token_urlsafe(24)
    sealed = encrypt_credentials_dict(
        {
            "user_token": user_token,
            "expires_in": expires_in,
            "granted": granted,
            "config_id": config_id,
        }
    )
    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "user_id": user_id,
            "provider": provider,
            "page_ids": page_ids,
            "sealed": sealed,
        }
    )
    await get_redis().set(_page_choice_key(ticket), payload, ex=_PAGE_CHOICE_TTL_SECONDS)
    return ticket


def _open_parked_choice(raw) -> dict | None:
    """Decode a parked choice and unseal its secrets; None when it is unreadable."""
    if raw is None:
        return None
    try:
        parked = json.loads(raw)
        parked["secrets"] = decrypt_credentials_dict(parked.pop("sealed", {}))
    except (ValueError, TypeError, KeyError):
        return None
    return parked


async def _peek_page_choice(ticket: str) -> dict | None:
    """Read a parked choice WITHOUT consuming it, so it can be checked before it is spent."""
    return _open_parked_choice(await get_redis().get(_page_choice_key(ticket)))


async def _take_page_choice(ticket: str) -> dict | None:
    """Read AND remove a parked choice in one step, so a ticket works once.

    The removal is the atomic part: of two requests that both passed their checks, only the one
    whose GETDEL finds the ticket may continue."""
    return _open_parked_choice(await get_redis().getdel(_page_choice_key(ticket)))


#: The whole code-to-channel exchange, in seconds. It is up to six Graph calls one after another
#: inside the browser's redirect, each allowed 8 s: a slow Meta kept the popup spinning for as long
#: as 48 s with nothing said. A deadline turns that into an answer the owner can act on.
OAUTH_EXCHANGE_BUDGET_SECONDS = 25.0


async def _bounded_exchange(
    session: AsyncSession,
    code: str,
    state_payload: dict,
    *,
    budget: float | None = None,
) -> tuple[str, str]:
    """`_meta_exchange_and_connect` under a total deadline.

    Running out of time is reported as Meta being unavailable (retryable), the same answer the
    caller already gives a Graph outage, because that is what it is from the owner's side.
    """
    limit = OAUTH_EXCHANGE_BUDGET_SECONDS if budget is None else budget
    try:
        async with asyncio.timeout(limit):
            return await _meta_exchange_and_connect(session, code, state_payload)
    except TimeoutError:
        raise ExternalProviderError(
            "Meta is taking too long to answer. Try connecting again in a minute.",
            retryable=True,
        ) from None


async def _meta_exchange_and_connect(
    session: AsyncSession, code: str, state_payload: dict
) -> tuple[str, str]:
    """code → user token → long-lived token → /me/accounts → connect the page.

    Returns (provider, display_name); raises on every failure so the callback
    redirects the browser with meta_error instead of a bare 500.
    """
    from app.core.db import bind_tenant

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
        swap = _graph_json(
            await http.get(
                f"{_GRAPH}/oauth/access_token",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            ),
            step="code exchange",
        )
        failure = _meta_graph_error(swap, step="code exchange")
        if failure:
            _logger.warning("meta_oauth.exchange_failed %s", failure)
            await _flag("link.code_exchange_failed", provider, tenant_id, _graph_fields(swap))
            raise ValidationError(failure[:200])
        user_token = swap.get("access_token")
        if not user_token:
            await _flag("link.code_exchange_failed", provider, tenant_id, {"reason": "no_token"})
            raise ValidationError("Meta rejected the authorization code.")

        # 2) Short-lived → LONG-LIVED user token (fb_exchange_token grant).
        #    A page token minted from a short-lived user token expires in
        #    about an hour and the channel would die silently; a page token
        #    minted from a long-lived user token does not expire. Tokens
        #    that do not expire (system-user access tokens from a business
        #    config_id) carry no expires_in and skip the exchange.
        expires_in = swap.get("expires_in")
        if swap.get("expires_in"):
            exchange_params = {
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": user_token,
            }
            if _config_id and provider == "instagram":
                # Business Login system-user tokens support the rolling
                # 60-day refresh contract documented by Meta.
                exchange_params["set_token_expires_in_60_days"] = "true"
            long_lived = _graph_json(
                await http.get(
                    f"{_GRAPH}/oauth/access_token",
                    params=exchange_params,
                ),
                step="long-lived exchange",
            )
            long_token = long_lived.get("access_token")
            if not long_token:
                failure = _meta_graph_error(long_lived, step="long-lived exchange")
                _logger.warning("meta_oauth.longlived_failed %s", failure)
                await _flag(
                    "link.code_exchange_failed",
                    provider,
                    tenant_id,
                    {"step": "long_lived", **_graph_fields(long_lived)},
                )
                raise ValidationError(
                    (failure or "Meta refused the long-lived token exchange.")[:200]
                )
            user_token = long_token
            expires_in = long_lived.get("expires_in", expires_in)

        # 2b) What the owner actually ticked. The dialog lets them untick a single permission and
        #     still continue, and a Facebook channel without posting or comment rights would show
        #     as connected and then fail on its first post. Refuse it here, naming what is missing.
        permissions = _graph_json(
            await http.get(f"{_GRAPH}/me/permissions", params={"access_token": user_token}),
            step="permissions",
        )
        granted = granted_scopes_from_permissions(permissions)
        if provider == "facebook":
            lacking = missing_facebook_scopes(granted)
            if lacking:
                _logger.warning("meta_oauth.facebook_scopes_missing %s", ",".join(lacking))
                await _flag("link.scopes_missing", provider, tenant_id, {"missing": list(lacking)})
                raise ValidationError(
                    "لم تُمنح كل صلاحيات فيسبوك المطلوبة للنشر والتعليقات والإحصاءات "
                    f"({', '.join(lacking)}). أعد الربط وفعّل كل الصلاحيات في نافذة فيسبوك."
                )

        # 3) Pages the operator manages, WITH their page tokens.
        accounts = _graph_json(
            await http.get(
                f"{_GRAPH}/me/accounts",
                params={"fields": _PAGE_FIELDS, "access_token": user_token},
            ),
            step="page listing",
        )
        failure = _meta_graph_error(accounts, step="page listing")
        if failure:
            _logger.warning("meta_oauth.accounts_failed %s", failure)
            await _flag(
                "link.code_exchange_failed",
                provider,
                tenant_id,
                {"step": "page_listing", **_graph_fields(accounts)},
            )
            raise ValidationError(failure[:200])

        all_pages = accounts.get("data", [])
        if not all_pages:
            # A Page owned by a Business Portfolio is NOT listed by /me/accounts even when the
            # operator manages it and granted every scope. Look it up through the portfolios, then
            # through the Pages named in the token's own grant.
            all_pages = await _business_portfolio_pages(http, user_token)
        if not all_pages:
            all_pages = await _granted_target_pages(http, user_token)
        if not all_pages:
            await _flag("link.no_pages", provider, tenant_id, {"granted": sorted(granted)})
            raise ValidationError(
                "لم يتم العثور على أي صفحة فيسبوك في حسابك — يجب إنشاء صفحة فيسبوك وتحديدها عند منح الصلاحيات."  # noqa: E501
            )

        # Evidence for support: which pages Meta returned and whether each carries an
        # Instagram business account. Ids and names only; never a token.
        _logger.info(
            "meta_oauth.pages provider=%s granted=%s pages=%s",
            provider,
            ",".join(sorted(granted)) if granted else "-",
            [
                {
                    "id": str(p.get("id")),
                    "name": p.get("name"),
                    "tasks": p.get("tasks"),
                    "ig": (p.get("instagram_business_account") or {}).get("id"),
                }
                for p in all_pages
            ],
        )
        pages = _messaging_pages(all_pages)
        if len(pages) > 1:
            # One channel holds one Page and the owner ticked several: ask which, instead of
            # silently taking the first. Nothing is stored yet — the choice finishes the connect.
            ticket = await _park_page_choice(
                tenant_id=tenant_id,
                user_id=str(state_payload.get("sub") or ""),
                provider=provider,
                user_token=user_token,
                expires_in=expires_in,
                granted=granted,
                config_id=_config_id,
                page_ids=[str(p["id"]) for p in pages],
            )
            raise PageChoiceRequired(ticket, _page_choices(pages))
        return await _connect_page(
            session,
            http,
            page=pages[0],
            provider=provider,
            tenant_id=tenant_id,
            user_token=user_token,
            expires_in=expires_in,
            granted=granted,
            config_id=_config_id,
        )


async def _connect_page(
    session: AsyncSession,
    http: httpx.AsyncClient,
    *,
    page: dict,
    provider: str,
    tenant_id: uuid.UUID,
    user_token: str,
    expires_in,
    granted,
    config_id: str,
) -> tuple[str, str]:
    """Store the channel for ONE chosen Page (credentials, webhook subscription, activation)."""
    from app.modules.billing.service import EntitlementService
    from app.modules.customers.routers.integrations import (
        _activate_verified_channel,
        _verification_metadata,
    )

    _config_id = config_id
    # 4) Credentials + routing identity per gateway contract:
    #    - the webhook routes inbound by config.account_id;
    #    - the Instagram gateway SENDS against the IG business account
    #      (/{ig-id}/messages with the PAGE token), so that id must ride
    #      the encrypted credentials too.
    page_token = page["access_token"]
    if provider == "facebook":
        # The Facebook spec verifies the PASTED page id against the token
        # (same anti-mismatch guard as WhatsApp), so the flow hands it the
        # page's own id and the spec's credential key.
        config = {"page_id": str(page["id"])}
        credentials = {"page_access_token": page_token}
    else:
        config = {"account_id": str(page["id"])}
        credentials = {"api_key": page_token}
    if provider == "instagram":
        ig_account = page.get("instagram_business_account") or {}
        ig_id = str(ig_account.get("id") or "")
        if not ig_id:
            page_title = page.get("name") or str(page.get("id") or "المحددة")
            await _flag(
                "link.no_instagram_account",
                provider,
                tenant_id,
                {"page_id": str(page.get("id")), "page_name": page.get("name")},
            )
            raise ValidationError(
                f"صفحة فيسبوك '{page_title}' غير مرتبطة بحساب إنستجرام احترافي — اربط الحساب في Meta Business Suite أولاً."  # noqa: E501
            )
        config["account_id"] = ig_id
        credentials["account_id"] = ig_id

    verified = await verify_channel_credentials(provider, credentials, config, client=http)

    # A channel that cannot receive provider webhooks is not connected.
    try:
        await _subscribe_page_to_app(
            http, page_id=str(page["id"]), page_token=page_token, provider=provider
        )
    except ExternalProviderError as exc:
        # Without this subscription nothing the customer sends would ever arrive.
        await _flag(
            "link.subscription_failed",
            provider,
            tenant_id,
            {"page_id": str(page["id"]), "reason": str(exc)[:200]},
        )
        raise

    from app.core.meta_tokens import token_expiry

    credentials["_meta"] = {
        "source_access_token": user_token,
        "page_id": str(page["id"]),
        "expires_at": token_expiry(expires_in),
        # Only Instagram is linked through a Business Login configuration; for Messenger and
        # Facebook the Instagram setting says nothing about their token.
        "refreshable": bool(provider == "instagram" and _config_id and expires_in),
    }

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

    verified_at = datetime.now(UTC).isoformat()
    connection_meta = _verification_metadata(
        verified_at=verified_at, display_name=verified.display_name
    )
    connection_meta["granted_scopes"] = granted
    integration_config = {
        **verified.identity_config,
        "_connection": connection_meta,
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

    display_name = verified.display_name or str(page.get("name") or page["id"])
    return provider, display_name


def _popup_html(result: dict, frontend_origin: str) -> str:
    """Small self-closing HTML page that posts the OAuth result to the opener.

    Uses multiple fallback channels:
    1. window.opener.postMessage()
    2. BroadcastChannel('meta_oauth')
    3. localStorage event ('meta_oauth_result')
    Displays a clear success or error banner so the user never sees a misleading message.
    """
    import html as _html
    import json as _json

    payload_json = _json.dumps(result)
    safe_json = payload_json.replace("<", "\\u003c").replace(">", "\\u003e")

    is_connected = "connected" in result
    is_choosing = "choose" in result
    error_val = result.get("error", "")

    if is_choosing:
        title_text = "اختر الصفحة"
        subtitle_text = "عدنا إلى صفحة الإعدادات لتختار الصفحة التي تريد ربطها."
        card_class = "success"
        icon_html = '<svg class="icon success-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'  # noqa: E501
        action_html = '<p class="hint">سيتم إغلاق هذه النافذة تلقائيًا...</p>'
    elif is_connected:
        raw_val = result["connected"]
        sep = raw_val.find(":")
        page_name = raw_val[sep + 1 :] if sep != -1 else raw_val
        title_text = "تم الربط بنجاح"
        subtitle_text = f"صفحة: {page_name}"
        card_class = "success"
        icon_html = '<svg class="icon success-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'  # noqa: E501
        action_html = '<p class="hint">سيتم إغلاق هذه النافذة تلقائيًا والعودة للإعدادات...</p>'
    else:
        title_text = "تعذر إتمام الربط"
        card_class = "error"
        icon_html = '<svg class="icon error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'  # noqa: E501

        s = str(error_val)
        if "Invalid Scopes" in s or "instagram_basic" in s:
            subtitle_text = "تطبيق Meta ينقصه صلاحيات إنستجرام: يرجى إضافة منتج Instagram Graph API وصلاحيات instagram_basic وinstagram_manage_messages في لوحة مطوري Meta."  # noqa: E501
        elif "access_denied" in s:
            subtitle_text = "أُلغيت الموافقة أو أن حسابك ليس مطوراً/مسؤولاً في تطبيق فيسبوك."
        elif "No messaging-capable page" in s or "لم يتم العثور على أي صفحة" in s:
            subtitle_text = (
                "لم يتم العثور على أي صفحة فيسبوك في حسابك، أو لم يتم تحديد صفحة عند منح الصلاحيات."  # noqa: E501
            )
        elif "غير مرتبطة بحساب إنستجرام" in s or "No Instagram professional account" in s:
            subtitle_text = (
                "صفحة فيسبوك المحددة غير مرتبطة بحساب إنستجرام احترافي (Business/Creator)."  # noqa: E501
            )
        elif s.startswith("meta_unavailable"):
            title_text = "فيسبوك غير متاح مؤقتاً"
            subtitle_text = (
                "خوادم فيسبوك لا تستجيب الآن. هذه ليست مشكلة في الإعدادات. أعد المحاولة بعد دقيقة."  # noqa: E501
            )
        elif "missing_code_or_state" in s:
            subtitle_text = "أُلغيت العملية أو لم يُرجع فيسبوك رمز التفويض."
        elif "invalid_state" in s:
            subtitle_text = "انتهت صلاحية جلسة الربط (10 دقائق). اضغط على زر الربط مجدداً."
        else:
            subtitle_text = s[:200]

        action_html = (
            '<button id="meta-oauth-close" type="button" class="btn-close">إغلاق النافذة</button>'
        )

    esc_title = _html.escape(title_text)
    esc_subtitle = _html.escape(subtitle_text)

    autoclose_flag = "1" if (is_connected or is_choosing) else "0"
    esc_origin = _html.escape(frontend_origin.rstrip("/"), quote=True)

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc_title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
    "IBM Plex Sans Arabic", sans-serif;
    background-color: #0c0d0e;
    color: #f3f4f6;
    padding: 20px;
    direction: rtl;
  }}
  .card {{
    background: #16181a;
    border: 1px solid #272a2e;
    border-radius: 16px;
    padding: 32px 24px;
    text-align: center;
    max-width: 440px;
    width: 100%;
    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
  }}
  .icon-wrapper {{
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 16px;
  }}
  .success .icon-wrapper {{
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid rgba(16, 185, 129, 0.3);
  }}
  .error .icon-wrapper {{
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid rgba(239, 68, 68, 0.3);
  }}
  .icon {{
    width: 28px;
    height: 28px;
  }}
  .success-icon {{ stroke: #10b981; }}
  .error-icon {{ stroke: #ef4444; }}
  h2 {{
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 10px;
  }}
  .success h2 {{ color: #10b981; }}
  .error h2 {{ color: #ef4444; }}
  .desc {{
    font-size: 13.5px;
    line-height: 1.6;
    color: #9ca3af;
    margin-bottom: 20px;
  }}
  .hint {{
    font-size: 12px;
    color: #6b7280;
  }}
  .btn-close {{
    display: inline-block;
    background: #272a2e;
    color: #f3f4f6;
    border: 1px solid #373b40;
    padding: 8px 24px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s ease;
  }}
  .btn-close:hover {{ background: #32363b; }}
</style>
</head>
<body>
<div class="card {card_class}">
  <div class="icon-wrapper">{icon_html}</div>
  <h2>{esc_title}</h2>
  <p class="desc">{esc_subtitle}</p>
  {action_html}
</div>
<script id="meta-oauth-data" type="application/json"
  data-origin="{esc_origin}" data-autoclose="{autoclose_flag}">{safe_json}</script>
<script src="{esc_origin}/meta-oauth-result.js"></script>
</body></html>"""


def _popup_response(result: dict, frontend_origin: str):
    """The OAuth result page, with headers that let it report back to the opener.

    Two things silently broke the "connected" confirmation although the channel
    itself connected fine:

    * COOP ``same-origin`` (stamped on every API response) severed
      ``window.opener`` after the round trip through facebook.com. It is relaxed
      for this one response.
    * The page's inline script never ran: ``/api/v1/...`` is proxied through
      Vercel, which stamps ``script-src 'self'`` on every path, and the API's own
      ``default-src 'none'`` blocks it too. The script is therefore an external
      same-origin file and the result travels as inert JSON data, so no inline
      code is needed and the site CSP stays strict.
    """
    from fastapi.responses import HTMLResponse

    origin = frontend_origin.rstrip("/")
    return HTMLResponse(
        _popup_html(result, frontend_origin),
        headers={
            "Content-Security-Policy": (
                f"default-src 'none'; script-src {origin}; style-src 'unsafe-inline'; "
                "img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            ),
            "Cross-Origin-Opener-Policy": "unsafe-none",
            "Cache-Control": "no-store",
        },
    )


class MetaOAuthPageChoiceIn(BaseModel):
    ticket: str = Field(min_length=16, max_length=128)
    page_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9]+$")


@meta_oauth_router.post(
    "/integrations/meta/oauth/choose-page", response_model=MetaOAuthChoosePageOut
)
async def meta_oauth_choose_page(
    body: MetaOAuthPageChoiceIn,
    session: DbSession,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Finish a connect that paused to ask which Page: store the channel for the chosen one.

    The ticket was parked for THIS tenant and user, works once, and only the Pages it was
    parked with can be chosen — a forged page id cannot reach another Page the user manages."""
    from app.core.db import bind_tenant

    # Check BEFORE spending the ticket. It used to be burned by the first request that touched
    # it, so a wrong id or a double click sent the owner back to the start of the OAuth.
    parked = await _peek_page_choice(body.ticket)
    if parked is None:
        # Gone (the 10 minutes ran out) and unreadable (a broken value) read the same to the
        # owner but need different fixes, so the trail tells them apart. Never the ticket itself.
        present = await get_redis().exists(_page_choice_key(body.ticket))
        reason = "unreadable" if present else "missing_or_expired"
        _logger.warning("meta_oauth.choice_ticket_invalid reason=%s", reason)
        await _flag("link.choice_ticket_invalid", None, ctx.tenant_id, {"reason": reason})
        raise ValidationError("This choice expired. Press connect again.")
    if parked["tenant_id"] != str(ctx.tenant_id) or parked["user_id"] != str(ctx.user.id):
        # Someone else is holding this ticket: that is tampering, not a slip. It dies here.
        await _take_page_choice(body.ticket)
        raise ValidationError("This choice was not started by you. Press connect again.")
    if body.page_id not in parked["page_ids"]:
        # The owner's own slip. The ticket is random and useless without being the owner, so
        # leaving it alive costs nothing and lets them choose again.
        raise ValidationError("That Page was not one of the choices. Choose one from the list.")
    if await _take_page_choice(body.ticket) is None:
        # A second request got here first (a double click): exactly one may go on.
        raise ValidationError("This choice expired. Press connect again.")

    provider = parked["provider"]
    secrets = parked["secrets"]
    await bind_tenant(session, ctx.tenant_id)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
    ) as http:
        # Page tokens are never parked: list the Pages again from the user token.
        accounts = _graph_json(
            await http.get(
                f"{_GRAPH}/me/accounts",
                params={"fields": _PAGE_FIELDS, "access_token": secrets["user_token"]},
            ),
            step="page listing",
        )
        failure = _meta_graph_error(accounts, step="page listing")
        if failure:
            _logger.warning("meta_oauth.choose_accounts_failed %s", failure)
            raise ValidationError(failure[:200])
        page = next((p for p in accounts.get("data", []) if str(p.get("id")) == body.page_id), None)
        if page is None:
            raise ValidationError("Meta no longer lists that Page for your account.")
        provider, display_name = await _connect_page(
            session,
            http,
            page=page,
            provider=provider,
            tenant_id=ctx.tenant_id,
            user_token=secrets["user_token"],
            expires_in=secrets.get("expires_in"),
            granted=secrets.get("granted"),
            config_id=secrets.get("config_id") or "",
        )
    return {"connected": f"{provider}:{display_name}"}


@meta_oauth_router.get("/integrations/meta/oauth/callback", include_in_schema=False)
async def meta_oauth_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
):
    """Meta redirects the operator's browser here with the authorization code.

    PUBLIC by design: the state JWT (15-minute TTL, server-signed) is the
    authorization — it was minted to a settings:write holder at start time.
    Every outcome posts back to the opener window via postMessage / BroadcastChannel —
    the operator never leaves the settings page. Meta's own dialog errors
    (access_denied, Invalid Scopes, etc.) are carried through verbatim."""

    from app.core.config import get_settings
    from app.core.db import bind_tenant

    frontend = get_settings().frontend_public_url.rstrip("/")

    def _back(marker: str, value: str, extra: dict | None = None):
        result = {"type": "META_OAUTH_RESULT"}
        if marker == "connected":
            result["connected"] = value
        else:
            result["error"] = value
        if extra:
            result.update(extra)
        return _popup_response(result, frontend)

    # Meta redirects here with error params when the DIALOG failed
    if (error or error_code or error_message) and not code:
        description = (error_description or error_message or "").strip()
        code_tag = error or (f"error_{error_code}" if error_code else "dialog_error")
        detail = f"{code_tag}:{description}" if description else code_tag
        _logger.warning(
            "meta_oauth.dialog_error error=%s code=%s desc=%s",
            error,
            error_code,
            description[:200],
        )
        await _flag(
            "link.window_closed" if error == "access_denied" else "link.code_exchange_failed",
            None,
            None,
            {"error": error, "error_code": error_code, "description": description[:200]},
        )
        return _back("error", detail)

    # Each early refusal below says WHY on the diagnostics trail. The state and the code are
    # credentials, so only the reason is recorded, never their values.
    async def _refuse(error: str, reason: str, provider: str | None = None):
        _logger.warning("meta_oauth.state_refused reason=%s", reason)
        await _flag("link.state_invalid", provider, None, {"reason": reason})
        return _back("error", error)

    if not code or not state:
        return await _refuse("missing_code_or_state", "missing_code_or_state")
    try:
        payload = decode_token(state)
    except Exception:
        return await _refuse("invalid_state", "undecodable")
    if payload.get("type") != "oauth_state":
        return await _refuse("invalid_state", "wrong_type")
    provider = payload.get("provider")
    if provider not in _META_PROVIDERS:
        return await _refuse("invalid_provider", "unknown_provider")

    try:
        await bind_tenant(session, uuid.UUID(str(payload["tenant_id"])))
        connected_provider, page_name = await _bounded_exchange(session, code, payload)
    except PageChoiceRequired as choice:
        await session.rollback()
        return _back(
            "choose",
            provider,
            {"choose": {"ticket": choice.ticket, "provider": provider, "pages": choice.choices}},
        )
    except ExternalProviderError as exc:
        # Meta (or the path to it) is down or rate limiting: say so, and say it is retryable.
        await session.rollback()
        _logger.warning("meta_oauth.provider_unavailable provider=%s reason=%s", provider, exc)
        await _flag("link.provider_unavailable", provider, None, {"reason": str(exc)[:200]})
        return _back("error", f"meta_unavailable:{str(exc)[:120]}")
    except DomainError as exc:
        await session.rollback()
        return _back("error", f"{provider}:{str(exc)[:120]}")
    except Exception as exc:
        _logger.exception("meta_oauth.connect_failed provider=%s", provider)
        await session.rollback()
        return _back("error", f"meta_exchange_failed:{type(exc).__name__}")

    return _back("connected", f"{connected_provider}:{page_name}")
