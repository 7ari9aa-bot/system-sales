"""WhatsApp Embedded Signup — the click-and-connect flow (spec: channels).

The owner presses the WhatsApp button on the channels page; Meta's own popup
opens; the store owner logs in with THEIR Meta account, creates/selects a
WhatsApp Business Account and a phone number; Meta hands this server a
one-time `code` plus the chosen `waba_id` / `phone_number_id`. We exchange the
code for a business token, subscribe our app to the WABA (so inbound messages
start flowing), verify the number against Graph, and store the integration.

Why this is a SEPARATE flow from meta_oauth.py: Embedded Signup is a JS-SDK
POPUP (not a redirect), it exchanges the code WITHOUT a redirect_uri, and its
product is a WABA + phone number rather than a Facebook Page. Same app, same
tenant, different product — so it gets its own file.

Meta console prerequisites (docs/META_SETUP.md §WhatsApp):
  * Facebook Login for Business enabled, with a configuration created from the
    Embedded Signup flow and Cloud API product → META_WHATSAPP_CONFIG_ID
  * the dashboard origin listed under Allowed Domains for the JavaScript SDK
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.errors import ConflictError, ExternalProviderError, NotFoundError, ValidationError
from app.core.secrets import decrypt_credentials_dict, encrypt_credentials_dict
from app.platform.identity.deps import DbSession, TenantContext, require_permission
from app.platform.platform.channel_specs.whatsapp import (
    COEXISTENCE_PLATFORM,
    coexistence_evidence,
)

logger = logging.getLogger(__name__)

whatsapp_signup_router = APIRouter()

#: Same pinned Graph release as the OAuth flow — one version for both dialogs
#: and calls, so the app's configuration and our requests never disagree.
_GRAPH_VERSION = "v27.0"
_GRAPH = f"https://graph.facebook.com/{_GRAPH_VERSION}"


class WhatsAppSignupStartOut(BaseModel):
    """Public values the browser needs to open Meta's popup — nothing secret."""

    app_id: str
    config_id: str
    graph_version: str


class WhatsAppSignupCompleteBody(BaseModel):
    """What the JS SDK popup hands back, plus the two ids from its session.

    ``onboarding_mode`` records which way the customer connected. Meta's coexistence flow ends with
    the FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING step, and a customer who picks it is choosing to
    keep using the WhatsApp Business app on the same number — not failing to connect. Refusing that
    step, or folding it into "cloud_api", would hide the difference from every screen afterwards.
    """

    code: str = Field(min_length=8, max_length=4096)
    waba_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    phone_number_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    # What the BROWSER asked for. The popup always asks Meta for the WhatsApp Business app flow,
    # so coexistence is the default; the stored mode is still decided from Meta's own answer about
    # the number (see _resolve_onboarding_mode), never from this field alone.
    onboarding_mode: str = Field(default="coexistence", pattern=r"^(cloud_api|coexistence)$")


class WhatsAppSignupCompleteOut(BaseModel):
    """Details of the newly configured WhatsApp channel integration."""

    id: str
    provider: str
    status: str
    display_name: str | None = None
    phone_number_id: str
    waba_id: str
    onboarding_mode: str = "coexistence"
    #: What Meta said about the number: ``verified`` (app + Cloud API together),
    #: ``not_on_business_app`` (Cloud API only) or ``unexpected_platform`` (refused).
    coexistence_status: str = "unknown"
    is_on_biz_app: bool | None = None
    platform_type: str | None = None
    #: How far the app's data (contacts + chat history) got: READY, CONTACTS_SYNC_PENDING, ...
    sync_state: str | None = None


def _whatsapp_config() -> tuple[str, str, str]:
    """(app_id, app_secret, embedded-signup config id) or a loud failure."""
    s = get_settings()
    app_id = s.meta_app_id.strip()
    app_secret = s.meta_app_secret.strip()
    config_id = s.meta_whatsapp_config_id.strip()
    if not (app_id and app_secret and config_id):
        # Name ONLY what is actually missing: the live production user test
        # showed app id + secret already set and just the WhatsApp config id
        # absent — listing all three sends an operator hunting for values that
        # are already there.
        missing = [
            name
            for name, value in (
                ("META_APP_ID", app_id),
                ("META_APP_SECRET", app_secret),
                ("META_WHATSAPP_CONFIG_ID", config_id),
            )
            if not value
        ]
        raise ValidationError(
            "WhatsApp Embedded Signup is not fully configured on this server — "
            f"set {', '.join(missing)} (create a Facebook Login for Business "
            "Embedded Signup configuration with the Cloud API product; see docs/META_SETUP.md)."
        )
    return app_id, app_secret, config_id


@whatsapp_signup_router.get(
    "/integrations/whatsapp/embedded-signup/start",
    response_model=WhatsAppSignupStartOut,
)
async def whatsapp_signup_start(
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Hand the browser the PUBLIC popup parameters (app id + config id).

    Only public values leave here: the popup is Meta's own page and the
    consent happens with the store owner's Meta account. The app SECRET stays
    on the server and is used only at completion time.
    """
    app_id, _secret, config_id = _whatsapp_config()
    return WhatsAppSignupStartOut(app_id=app_id, config_id=config_id, graph_version=_GRAPH_VERSION)


async def _exchange_code_for_token(
    http: httpx.AsyncClient, *, app_id: str, app_secret: str, code: str
) -> tuple[str, str | None]:
    """code → business token. Embedded Signup sends NO redirect_uri."""
    try:
        response = await http.get(
            f"{_GRAPH}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code,
            },
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not reach Meta to complete the WhatsApp connection. Try again."
        ) from None
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError("Meta is temporarily unavailable. Try again.", retryable=True)
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError("Meta returned an invalid token response.") from None
    if not response.is_success or not isinstance(payload, dict) or payload.get("error"):
        raise ValidationError("Meta rejected the WhatsApp authorization code. Press connect again.")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValidationError(
            "Meta returned no access token for this WhatsApp signup. Press connect again."
        )
    from app.core.meta_tokens import token_expiry

    return token, token_expiry(payload.get("expires_in"))


async def _phone_display_name(
    http: httpx.AsyncClient, *, phone_number_id: str, token: str
) -> str | None:
    """The verified business name / display number, for the settings UI.

    Cosmetic: the connection is verified separately, so a network failure here must
    not fail a signup the owner already completed in Meta's popup."""
    try:
        response = await http.get(
            f"{_GRAPH}/{phone_number_id}",
            params={"fields": "display_phone_number,verified_name"},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.RequestError:
        # This is presentation metadata only; a transient failure must not
        # discard an otherwise valid customer authorization.
        return None
    if response.is_error:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return str(payload.get("verified_name") or payload.get("display_phone_number") or "") or None


async def _verify_phone_belongs_to_waba(
    http: httpx.AsyncClient, *, waba_id: str, phone_number_id: str, token: str
) -> None:
    """Reject a tampered or inconsistent signup before subscribing/storing it."""
    params = {"fields": "id", "limit": "100"}
    for _page in range(100):
        try:
            response = await http.get(
                f"{_GRAPH}/{waba_id}/phone_numbers",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError:
            raise ExternalProviderError(
                "Could not verify that this WhatsApp number belongs to the selected business. "
                "Try again."
            ) from None
        if response.status_code == 429 or response.status_code >= 500:
            raise ExternalProviderError(
                "Meta is temporarily unavailable while verifying the WhatsApp number.",
                retryable=True,
            )
        try:
            payload = response.json()
        except ValueError:
            raise ExternalProviderError(
                "Meta returned an invalid WhatsApp account response."
            ) from None
        if not response.is_success or not isinstance(payload, dict) or payload.get("error"):
            raise ValidationError(
                "Meta could not verify the selected WhatsApp business account. "
                "Reopen signup and try again."
            )
        phone_numbers = payload.get("data")
        if not isinstance(phone_numbers, list):
            raise ExternalProviderError("Meta returned an invalid WhatsApp number list.")
        if any(
            isinstance(number, dict) and str(number.get("id") or "") == phone_number_id
            for number in phone_numbers
        ):
            return
        paging = payload.get("paging") or {}
        if not isinstance(paging, dict):
            raise ExternalProviderError("Meta returned an invalid WhatsApp number cursor.")
        cursors = paging.get("cursors") or {}
        if not isinstance(cursors, dict):
            raise ExternalProviderError("Meta returned an invalid WhatsApp number cursor.")
        after = cursors.get("after")
        if not paging.get("next"):
            break
        if not isinstance(after, str) or not after:
            raise ExternalProviderError("Meta returned an invalid WhatsApp number cursor.")
        params["after"] = after
    else:
        raise ExternalProviderError("Meta returned too many WhatsApp number pages to verify.")

    raise ValidationError(
        "The selected WhatsApp number does not belong to the selected business account."
    )


async def _subscribe_app_to_waba(http: httpx.AsyncClient, *, waba_id: str, token: str) -> None:
    """Subscribe our app to the WABA — without this NO inbound message arrives.

    A silent failure here would connect a number that can never receive
    anything, so it raises and the caller reports it instead of storing a
    half-working integration.
    """
    try:
        response = await http.post(
            f"{_GRAPH}/{waba_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not subscribe the WhatsApp account to this app. Try again."
        ) from None
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(
            "Meta is temporarily unavailable while setting up WhatsApp webhooks.",
            retryable=True,
        )
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError(
            "Meta returned an invalid webhook subscription response."
        ) from None
    if (
        not response.is_success
        or not isinstance(payload, dict)
        or payload.get("success") is not True
    ):
        raise ExternalProviderError(
            "Meta refused the WhatsApp webhook subscription — check the app's "
            "whatsapp_business_messaging permission, then retry.",
            retryable=False,
        )


async def _phone_status(http: httpx.AsyncClient, *, phone_number_id: str, token: str) -> str | None:
    """The number's connection status (``CONNECTED`` is the only one that can send and receive)."""
    try:
        response = await http.get(
            f"{_GRAPH}/{phone_number_id}",
            params={"fields": "status"},
            headers={"Authorization": f"Bearer {token}"},
        )
        payload = response.json() if not response.is_error else None
    except (httpx.RequestError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    return str(status).upper() if status else None


#: What we record (and show the owner) about Meta's answer on coexistence.
COEXISTENCE_VERIFIED = "verified"
COEXISTENCE_NOT_ON_APP = "not_on_business_app"


async def _number_platform_facts(
    http: httpx.AsyncClient, *, phone_number_id: str, token: str
) -> dict:
    """Meta's own answer about WHERE this number runs — or a loud failure, never a guess.

    ``is_on_biz_app`` + ``platform_type`` are the only documented proof that a number runs on the
    WhatsApp Business app and the Cloud API at the same time. A connect that cannot read them must
    not record a mode: assuming ``cloud_api`` is what made every Business App number look like a
    plain API number, and assuming coexistence would skip a registration the number still needs.
    """
    from app.platform.platform.channel_specs.whatsapp import number_platform_facts

    try:
        response = await http.get(
            f"{_GRAPH}/{phone_number_id}",
            params={"fields": "is_on_biz_app,platform_type"},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not read this WhatsApp number's state from Meta. Press connect again.",
            retryable=True,
        ) from None
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(
            "Meta is temporarily unavailable while checking the WhatsApp number.",
            retryable=True,
        )
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError(
            "Meta returned an invalid response for this WhatsApp number.", retryable=True
        ) from None
    if not response.is_success or not isinstance(payload, dict) or payload.get("error"):
        raise ValidationError(
            "Meta could not report whether this number runs on the WhatsApp Business app. "
            "Reopen the connect window and try again."
        )
    facts = number_platform_facts(payload)
    if facts["is_on_biz_app"] is None:
        raise ExternalProviderError(
            "Meta did not report whether this WhatsApp number runs on the WhatsApp Business app. "
            "Press connect again.",
            retryable=True,
        )
    return facts


def _resolve_onboarding_mode(facts: dict, requested: str) -> tuple[str, str]:
    """The mode to STORE, from Meta's answer — plus the status the settings screen shows.

    ``requested`` is only a hint for the log: the popup can report a mode for a number that never
    entered the Business App flow, and it cannot know what Meta will say about the number.
    """
    if coexistence_evidence(facts):
        return "coexistence", COEXISTENCE_VERIFIED
    if facts.get("is_on_biz_app") is True:
        platform = facts.get("platform_type") or "unknown"
        raise ValidationError(
            "Meta reports this WhatsApp number is on the WhatsApp Business app, but its platform "
            f"is {platform} instead of {COEXISTENCE_PLATFORM}. That is not the documented "
            "coexistence state, so nothing was connected. Connect the number again from the "
            "WhatsApp Business app, or move it to the Cloud API first."
        )
    logger.info(
        "whatsapp.signup_not_on_business_app_rejected requested=%s platform=%s",
        requested,
        facts.get("platform_type"),
    )
    raise ValidationError(
        "This FIHRIST connection is for an existing WhatsApp Business app number. "
        "Meta reports that this number is not currently on the WhatsApp Business app, "
        "so it was not connected. Open WhatsApp Business on the phone and start the "
        "Business App coexistence signup again."
    )


def _register_error(response: httpx.Response) -> ExternalProviderError:
    """What to tell the owner when Meta refuses to register the number, by Meta's own error.

    The code, subcode and Meta's text are kept in the message after the plain-language reason, so
    a support request carries what Meta actually said instead of a generic "finish verifying".
    """
    code = subcode = None
    meta_text = ""
    try:
        error = response.json().get("error") or {}
        code = error.get("code")
        subcode = error.get("error_subcode")
        meta_text = str(error.get("error_user_msg") or error.get("message") or "").strip()
    except (ValueError, AttributeError):
        pass

    # (message, retryable) per documented Meta code.
    known: dict[int, tuple[str, bool]] = {
        133016: (
            "Meta stopped registering this number after too many attempts. "
            "Wait 72 hours, then connect again.",
            False,
        ),
        133005: (
            "The two-step verification PIN on this number does not match. Remove or reset the "
            "PIN in WhatsApp Manager, then connect again.",
            False,
        ),
        133006: (
            "This number must be verified again with Meta before it can be registered. "
            "Verify it in the Facebook window, then connect again.",
            False,
        ),
        133008: (
            "Too many wrong two-step PIN attempts on this number. Wait before connecting again.",
            False,
        ),
        133009: (
            "The two-step PIN was entered too quickly after the last attempt. "
            "Wait a minute, then connect again.",
            True,
        ),
        133010: (
            "Meta says this number is not registered yet. Connect again to finish registering it.",
            True,
        ),
        133015: (
            "This number was deleted recently and cannot be registered yet. "
            "Wait a few minutes, then connect again.",
            True,
        ),
        190: (
            "Meta no longer accepts the connection to your Facebook account. "
            "Connect again and approve every permission.",
            False,
        ),
        10: (
            "Meta says this app lacks permission to register the number. "
            "Connect again and approve the WhatsApp permissions.",
            False,
        ),
        200: (
            "Meta says this app lacks permission to register the number. "
            "Connect again and approve the WhatsApp permissions.",
            False,
        ),
        80007: (
            "Meta is limiting requests for this account right now. Wait a few minutes, then "
            "connect again.",
            True,
        ),
    }
    reason, retryable = known.get(
        code if isinstance(code, int) else -1,
        (
            "Meta refused to register this WhatsApp number. Finish verifying the number in the "
            "Facebook window, then connect again.",
            False,
        ),
    )
    detail = f" [Meta {code}{f'/{subcode}' if subcode else ''}"
    detail += f": {meta_text[:160]}]" if meta_text else "]"
    return ExternalProviderError(reason + (detail if code is not None else ""), retryable=retryable)


async def _register_phone_number(
    http: httpx.AsyncClient,
    *,
    phone_number_id: str,
    token: str,
    pin: str | None = None,
) -> str | None:
    """Register the verified number with Cloud API; return the PIN now set (None if not needed).

    Meta: a number only sends and receives once it is registered, and registering is an API call
    (WhatsApp Manager and the App Dashboard cannot do it). The call needs a 6-digit two-step PIN.
    For a number without one it becomes the number's new PIN, so we keep it (encrypted) for the
    owner to recover the number later.

    * A number that is already CONNECTED is left alone: registering again would burn one of the 10
      attempts Meta allows per 72 hours (error 133016 then locks the number for 72 hours).
    * A status we could not READ is not "not connected". It fails the connect as retryable instead
      of spending an attempt on a guess.
    * ``pin`` is the PIN a previous, interrupted attempt may already have set. Reusing it keeps a
      lost response from leaving the number on a PIN nobody stored.
    """
    status = await _phone_status(http, phone_number_id=phone_number_id, token=token)
    if status == "CONNECTED":
        return None
    if status is None:
        raise ExternalProviderError(
            "Could not read the WhatsApp number's status from Meta. Press connect again.",
            retryable=True,
        )
    pin = pin or f"{secrets.randbelow(1_000_000):06d}"
    try:
        response = await http.post(
            f"{_GRAPH}/{phone_number_id}/register",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "pin": pin},
        )
    except httpx.RequestError:
        # The request may have reached Meta and set this PIN. Park it before failing so the retry
        # registers with the SAME one.
        await _remember_pending_pin(phone_number_id, pin)
        raise ExternalProviderError(
            "Could not reach Meta to register the WhatsApp number. Press connect again.",
            retryable=True,
        ) from None
    if response.is_error:
        raise _register_error(response)
    await _forget_pending_pin(phone_number_id)
    return pin


#: A PIN parked after an ambiguous register call. Redis, not Postgres: it is transport state for a
#: retry minutes away, and a number registered on a PIN is recoverable by the owner through Meta.
_PENDING_PIN_TTL_SECONDS = 24 * 60 * 60


def _pending_pin_key(phone_number_id: str) -> str:
    return f"whatsapp:pending_register_pin:{phone_number_id}"


async def _remember_pending_pin(phone_number_id: str, pin: str) -> None:
    from app.core.redis import get_redis

    try:
        await get_redis().set(
            _pending_pin_key(phone_number_id),
            json.dumps(encrypt_credentials_dict({"pin": pin})),
            ex=_PENDING_PIN_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 - parking is best effort; the connect error is what matters
        logger.warning("whatsapp.pending_pin_not_parked phone_number_id=%s", phone_number_id)


async def _take_pending_pin(phone_number_id: str) -> str | None:
    from app.core.redis import get_redis

    try:
        raw = await get_redis().get(_pending_pin_key(phone_number_id))
        if raw is None:
            return None
        return decrypt_credentials_dict(json.loads(raw)).get("pin")
    except Exception:  # noqa: BLE001
        return None


async def _forget_pending_pin(phone_number_id: str) -> None:
    from app.core.redis import get_redis

    try:
        await get_redis().delete(_pending_pin_key(phone_number_id))
    except Exception:  # noqa: BLE001
        pass


def _parse_instant(value: object) -> datetime | None:
    """An ISO timestamp from config, or None when it is absent/unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _start_coexistence_sync(
    session,
    tenant_id,
    *,
    integration,
    phone_number_id: str,
    waba_id: str,
    token: str,
) -> str:
    """Ask Meta for the app's contacts and chat history — now, and once.

    Meta accepts each of these requests ONCE per connection and only inside 24 hours of onboarding,
    so it is sent at the end of the connect instead of waiting for a worker that may never run.
    A failure is recorded on the channel (``sync_error``) and retried by the next connect attempt;
    it never turns a connected number into a failed connect, because the number IS connected.

    Order matters and used to be wrong: the channel row is COMMITTED before Meta is asked. Meta
    answers the request immediately and starts pushing ``history`` / ``smb_app_state_sync``
    webhooks within seconds, and a webhook for a number whose channel is still only flushed in an
    open transaction cannot be routed: those messages would be dropped with nothing to retry them.
    """
    from app.applications.apparel.modules.conversations import whatsapp_sync

    # The channel must exist for the webhook that is about to arrive, not for the next request.
    commit = getattr(session, "commit", None)
    if callable(commit):
        await commit()

    config = dict(integration.config or {})
    epoch = whatsapp_sync.epoch_for(config)
    completed_at = _parse_instant(config.get("coexistence_verified_at")) or datetime.now(UTC)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False
        ) as http:
            runs = await whatsapp_sync.request_all(
                session,
                tenant_id,
                phone_number_id=phone_number_id,
                waba_id=waba_id,
                epoch=epoch,
                onboarding_completed_at=completed_at,
                token=token,
                http=http,
            )
    except Exception as exc:  # noqa: BLE001 - a sync fault must not fail a working connection
        logger.warning(
            "whatsapp.coexistence_sync_not_started tenant=%s phone_number_id=%s",
            tenant_id,
            phone_number_id,
            exc_info=True,
        )
        config["sync_error"] = type(exc).__name__
        integration.config = config
        await session.flush()
        return whatsapp_sync.STATE_CONNECTED_PENDING_SYNC

    state = whatsapp_sync.channel_sync_state(
        runs.get(whatsapp_sync.WHATSAPP_SYNC_CONTACTS),
        runs.get(whatsapp_sync.WHATSAPP_SYNC_HISTORY),
    )
    config["sync_state"] = state
    config.pop("sync_error", None)
    integration.config = config
    await session.flush()
    return state


async def _retry_pending_sync(
    session, tenant_id, integration, *, phone_number_id: str, waba_id: str
) -> None:
    """A replayed connect finishes a sync that did not start the first time.

    Only when the channel is coexistence and the sync is not settled: the request may already have
    been sent (the run row says so) and then nothing happens, which is exactly the protection we
    want around Meta's one-shot request.
    """
    from app.applications.apparel.modules.conversations import whatsapp_sync

    config = integration.config if isinstance(integration.config, dict) else {}
    if str(config.get("onboarding_mode") or "") != "coexistence":
        return
    if whatsapp_sync.is_ready(str(config.get("sync_state") or "")):
        return
    try:
        stored = decrypt_credentials_dict(integration.credentials or {})
    except Exception:  # noqa: BLE001 - unreadable credentials are the connect flow's problem
        return
    token = stored.get("access_token")
    if not isinstance(token, str) or not token:
        return
    await _start_coexistence_sync(
        session,
        tenant_id,
        integration=integration,
        phone_number_id=phone_number_id,
        waba_id=waba_id,
        token=token,
    )


async def _prepare_number(
    http: httpx.AsyncClient,
    *,
    waba_id: str,
    phone_number_id: str,
    token: str,
    requested_mode: str,
) -> tuple[str, str, dict, str | None]:
    """Settle the number's real mode, register it only when it needs it, subscribe the app.

    Returns ``(onboarding_mode, coexistence_status, platform_facts, registration_pin)``.

    The order matters and is Meta's, not ours: a number that already lives on the WhatsApp
    Business app is registered there and must NOT be registered again (a second register spends
    one of the 10 attempts Meta allows per 72 hours, can lock the number with 133016, and invents
    a two-step PIN the app owner never set). A Cloud-API-only number still has to be registered,
    and that is the step Meta can refuse — so it happens BEFORE the subscription, which would
    otherwise leave an orphaned webhook subscription on the customer's WABA every time it fails.
    """
    platform_facts = await _number_platform_facts(
        http, phone_number_id=phone_number_id, token=token
    )
    onboarding_mode, coexistence_status = _resolve_onboarding_mode(platform_facts, requested_mode)
    registration_pin: str | None = None
    if onboarding_mode == "coexistence":
        # A coexistence number is already registered inside the Business app, and
        # _resolve_onboarding_mode refuses every number that is not coexistence — so this is the
        # only branch a connect can take. The register branch below is kept for the day a
        # Cloud-API-only number is allowed back in; today it cannot be reached from this route.
        logger.info(
            "whatsapp.coexistence_number_left_registered phone_number_id=%s", phone_number_id
        )
    else:
        registration_pin = await _register_phone_number(
            http,
            phone_number_id=phone_number_id,
            token=token,
            pin=await _take_pending_pin(phone_number_id),
        )
    await _subscribe_app_to_waba(http, waba_id=waba_id, token=token)
    return onboarding_mode, coexistence_status, platform_facts, registration_pin


@whatsapp_signup_router.post(
    "/integrations/whatsapp/embedded-signup/complete",
    response_model=WhatsAppSignupCompleteOut,
    status_code=201,
)
async def whatsapp_signup_complete(
    body: WhatsAppSignupCompleteBody,
    session: DbSession,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Finish the popup: exchange → subscribe → verify → store the channel."""
    from app.platform.billing.service import EntitlementService
    from app.applications.apparel.modules.customers.routers.integrations import (
        _activate_verified_channel,
        _verification_metadata,
        audit_channel_connected,
    )
    from app.platform.platform.integration_verifier import verify_channel_credentials
    from app.platform.platform.models import Integration

    app_id, app_secret, _config_id = _whatsapp_config()
    tenant_id = ctx.tenant_id

    existing = (
        await session.execute(_select_integration(tenant_id, "whatsapp"))
    ).scalar_one_or_none()
    if existing is not None and existing.status == "disabled":
        raise ValidationError("This channel was permanently disabled and cannot be reconnected.")
    if existing is None:
        await EntitlementService.ensure_channel_allowed(session, tenant_id, "whatsapp")
    elif _already_connected_to(existing, body):
        # The popup's code works once. When the first answer was lost, the same request comes
        # again (a retry, or the owner pressing connect once more), and exchanging the spent
        # code would end in "Meta rejected the authorization code" about a channel that is in
        # fact connected. Say what is true instead, without touching Meta: a second exchange,
        # register or subscribe would each spend a code or one of the 10 register attempts.
        logger.info(
            "whatsapp.embedded_signup_replayed tenant=%s phone_number_id=%s",
            tenant_id,
            body.phone_number_id,
        )
        await _retry_pending_sync(
            session,
            tenant_id,
            existing,
            phone_number_id=body.phone_number_id,
            waba_id=body.waba_id,
        )
        return _connected_result(existing, body)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False
    ) as http:
        token, token_expires_at = await _exchange_code_for_token(
            http, app_id=app_id, app_secret=app_secret, code=body.code
        )
        await _verify_phone_belongs_to_waba(
            http,
            waba_id=body.waba_id,
            phone_number_id=body.phone_number_id,
            token=token,
        )
        display_name = await _phone_display_name(
            http, phone_number_id=body.phone_number_id, token=token
        )
        # The SAME verification the manual connect runs: the token must own
        # the phone number id it claims, or nothing is stored.
        verified = await verify_channel_credentials(
            "whatsapp",
            {"access_token": token},
            {"phone_number_id": body.phone_number_id},
            client=http,
        )
        prepared = await _prepare_number(
            http,
            waba_id=body.waba_id,
            phone_number_id=body.phone_number_id,
            token=token,
            requested_mode=body.onboarding_mode,
        )
        onboarding_mode, coexistence_status, platform_facts, registration_pin = prepared

    verified_at = datetime.now(UTC).isoformat()
    integration_config = {
        **verified.identity_config,
        # The WABA id is not used for tenant resolution (phone_number_id is),
        # but it is what future template/quality calls address.
        "waba_id": body.waba_id,
        # Which way the number really runs, as Meta reported it. Coexistence means the WhatsApp
        # Business app keeps working on this number alongside the API, which changes what a screen
        # says about replies typed there, and which lifecycle events to expect.
        "onboarding_mode": onboarding_mode,
        # What the browser asked for, kept for support: a mismatch with onboarding_mode is the
        # difference between "the popup asked for the app flow" and "Meta said the number is on
        # the app". Only the second one is a fact.
        "onboarding_mode_requested": body.onboarding_mode,
        "coexistence_status": coexistence_status,
        "is_on_biz_app": platform_facts["is_on_biz_app"],
        "platform_type": platform_facts["platform_type"],
        "_connection": _verification_metadata(
            verified_at=verified_at, display_name=display_name or verified.display_name
        ),
    }
    if coexistence_status == COEXISTENCE_VERIFIED:
        # The clock Meta's 24-hour sync window runs from (contacts + history requests must be
        # sent inside it), recorded once at the moment the number proved it runs both ways.
        integration_config["coexistence_verified_at"] = verified_at
    secrets_to_store = {"access_token": token}
    secrets_to_store["_meta"] = {
        "expires_at": token_expires_at,
        "refreshable": bool(_config_id and token_expires_at),
    }
    if registration_pin:
        # Needed to change the PIN or delete the number later; never shown, never logged.
        secrets_to_store["registration_pin"] = registration_pin
    encrypted = encrypt_credentials_dict(secrets_to_store)

    if existing is None:
        integration = Integration(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider="whatsapp",
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
    try:
        await session.flush()
    except IntegrityError:
        # The unique index covers provider identity across tenants. Never expose the other
        # tenant or any account detail.
        raise ConflictError(
            "This WhatsApp number is already connected to another workspace."
        ) from None

    # The manual connect writes this row; the one-click flow redirects the same webhook traffic
    # and used to leave no trace. Shared helper so the two ways in cannot drift apart.
    await audit_channel_connected(
        session,
        tenant_id,
        ctx.user.id,
        integration,
        is_new=existing is None,
        extra={
            "via": "embedded_signup",
            "phone_number_id": body.phone_number_id,
            "waba_id": body.waba_id,
            "onboarding_mode": onboarding_mode,
            "coexistence_status": coexistence_status,
        },
    )

    sync_state: str | None = None
    if onboarding_mode == "coexistence":
        # Contacts + history, requested immediately: the window is 24 hours and Meta grants each
        # request once per connection.
        sync_state = await _start_coexistence_sync(
            session,
            tenant_id,
            integration=integration,
            phone_number_id=body.phone_number_id,
            waba_id=body.waba_id,
            token=token,
        )

    logger.info(
        "whatsapp.embedded_signup_connected tenant=%s phone_number_id=%s waba=%s",
        tenant_id,
        body.phone_number_id,
        body.waba_id,
    )
    return {
        "id": str(integration.id),
        "provider": "whatsapp",
        "status": integration.status,
        "display_name": display_name or verified.display_name,
        "phone_number_id": body.phone_number_id,
        "waba_id": body.waba_id,
        "onboarding_mode": onboarding_mode,
        "coexistence_status": coexistence_status,
        "is_on_biz_app": platform_facts["is_on_biz_app"],
        "platform_type": platform_facts["platform_type"],
        "sync_state": sync_state,
    }


def _already_connected_to(integration, body: WhatsAppSignupCompleteBody) -> bool:
    """True when this tenant's live WhatsApp channel IS the number and account being completed.

    Only a channel that works qualifies. One that needs reconnecting (``reauth_required``,
    ``disconnected``...) has to go through the whole link again, or a dead token stays dead."""
    config = integration.config if isinstance(integration.config, dict) else {}
    return (
        integration.status == "active"
        and str(config.get("phone_number_id") or "") == body.phone_number_id
        and str(config.get("waba_id") or "") == body.waba_id
    )


def _connected_result(integration, body: WhatsAppSignupCompleteBody) -> dict:
    """The answer a finished connect gives, from the stored row (never a credential)."""
    config = integration.config if isinstance(integration.config, dict) else {}
    connection = config.get("_connection")
    display_name = connection.get("display_name") if isinstance(connection, dict) else None
    # The mode comes from what was STORED, not from this request: a replay of a coexistence
    # connect must not answer "cloud_api" and hide the app from every screen afterwards.
    stored_mode = str(config.get("onboarding_mode") or body.onboarding_mode)
    stored_status = str(config.get("coexistence_status") or "unknown")
    stored_on_app = config.get("is_on_biz_app")
    return {
        "id": str(integration.id),
        "provider": "whatsapp",
        "status": integration.status,
        "display_name": display_name,
        "phone_number_id": body.phone_number_id,
        "waba_id": body.waba_id,
        "onboarding_mode": stored_mode,
        "coexistence_status": stored_status,
        "is_on_biz_app": stored_on_app if isinstance(stored_on_app, bool) else None,
        "platform_type": config.get("platform_type") or None,
        "sync_state": config.get("sync_state") or None,
    }


def _select_integration(tenant_id, provider: str):
    """The tenant's channel row for this provider (one per provider)."""
    from sqlalchemy import select

    from app.platform.platform.models import Integration

    return select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.provider == provider,
        Integration.kind == "channel",
    )


class WhatsAppSyncRunOut(BaseModel):
    """One half of the data sync as the screen shows it: a word, a bar, a count."""

    sync_type: str
    state: str
    progress: int = 0
    messages_stored: int = 0
    chunks: int = 0
    requested_at: str | None = None
    deadline_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    #: A reservation whose answer never arrived: visible, and reconcilable without a second request.
    needs_attention: bool = False
    attention: dict | None = None


class WhatsAppCoexistenceStatusOut(BaseModel):
    """Whether the app and FIHRIST are actually sharing this number, and how far the data got.

    ``sync_state`` is recomputed from the sync rows on every read, so a history chunk that landed
    a second ago is already reflected. ``offboarded`` carries Meta's own reason for a removal —
    the one thing that tells the owner the number needs linking again rather than waiting.
    """

    provider: str = "whatsapp"
    connected: bool = False
    status: str | None = None
    display_name: str | None = None
    phone_number_id: str | None = None
    onboarding_mode: str | None = None
    coexistence_status: str = "unknown"
    is_on_biz_app: bool | None = None
    platform_type: str | None = None
    sync_state: str
    sync_label: dict[str, str]
    ready: bool = False
    offboarded: bool = False
    disconnect_event: str | None = None
    disconnect_reason: str | None = None
    deadline_at: str | None = None
    needs_attention: bool = False
    #: How much of the number's 20-per-second send budget is in use, and what 130429 means.
    throughput: dict | None = None
    contacts: WhatsAppSyncRunOut | None = None
    history: WhatsAppSyncRunOut | None = None


@whatsapp_signup_router.get(
    "/integrations/whatsapp/coexistence-status",
    response_model=WhatsAppCoexistenceStatusOut,
)
async def whatsapp_coexistence_status(
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    """The live state of the WhatsApp Business app link, for the inbox and the settings card.

    Read-only and cheap: it answers from our own rows, never from Meta. A workspace with no
    WhatsApp channel gets ``connected: false`` and the neutral "about to sync" state instead of a
    404, because the inbox asks this on every open and a missing channel is not an error.
    """
    from app.applications.apparel.modules.conversations import whatsapp_sync

    integration = (
        await ctx.session.execute(_select_integration(ctx.tenant_id, "whatsapp"))
    ).scalar_one_or_none()
    if integration is None:
        return WhatsAppCoexistenceStatusOut(
            sync_state=whatsapp_sync.STATE_CONNECTED_PENDING_SYNC,
            sync_label=whatsapp_sync.STATE_COPY[whatsapp_sync.STATE_CONNECTED_PENDING_SYNC],
        )

    config = integration.config if isinstance(integration.config, dict) else {}
    health = integration.webhook_health if isinstance(integration.webhook_health, dict) else {}
    removed = (
        health.get("partner_removed") if isinstance(health.get("partner_removed"), dict) else {}
    )
    snapshot = await whatsapp_sync.sync_snapshot(
        ctx.session,
        ctx.tenant_id,
        config=config,
        offboarded=bool(removed),
    )
    connection = config.get("_connection") if isinstance(config.get("_connection"), dict) else {}
    from app.applications.apparel.modules.conversations.gateway import whatsapp_throughput

    throughput = await whatsapp_throughput.usage(str(config.get("phone_number_id") or ""))
    return WhatsAppCoexistenceStatusOut(
        connected=integration.status in ("active", "connected"),
        status=integration.status,
        display_name=connection.get("display_name") or None,
        phone_number_id=str(config.get("phone_number_id") or "") or None,
        onboarding_mode=snapshot["onboarding_mode"],
        coexistence_status=snapshot["coexistence_status"],
        is_on_biz_app=snapshot["is_on_biz_app"],
        platform_type=snapshot["platform_type"],
        sync_state=snapshot["sync_state"],
        sync_label=snapshot["sync_label"],
        ready=snapshot["ready"],
        offboarded=snapshot["offboarded"],
        disconnect_event=(removed.get("event") or None) if removed else None,
        disconnect_reason=(removed.get("reason") or None) if removed else None,
        deadline_at=snapshot["deadline_at"],
        needs_attention=snapshot["needs_attention"],
        throughput=throughput,
        contacts=snapshot["contacts"],
        history=snapshot["history"],
    )


class WhatsAppSyncReconcileIn(BaseModel):
    """Which half to close, and what the operator concluded."""

    sync_type: str
    note: str | None = None


@whatsapp_signup_router.post(
    "/integrations/whatsapp/coexistence-reconcile",
    response_model=WhatsAppCoexistenceStatusOut,
)
async def whatsapp_coexistence_reconcile(
    payload: WhatsAppSyncReconcileIn,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Close a stuck sync reservation, then return the fresh picture.

    Deliberately local: Meta allows ONE request per sync kind, so "try again" is never an option
    here. The operator decides the outcome is unknown, the run is marked failed with their note,
    and the channel tells the merchant to re-link instead of silently waiting forever.
    """
    from app.applications.apparel.modules.conversations import whatsapp_sync

    if payload.sync_type not in (
        whatsapp_sync.WHATSAPP_SYNC_CONTACTS,
        whatsapp_sync.WHATSAPP_SYNC_HISTORY,
    ):
        raise ValidationError(f"Unknown WhatsApp sync type: {payload.sync_type}")

    integration = (
        await ctx.session.execute(_select_integration(ctx.tenant_id, "whatsapp"))
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("This workspace has no WhatsApp channel to reconcile.")

    config = integration.config if isinstance(integration.config, dict) else {}
    await whatsapp_sync.reconcile_run(
        ctx.session,
        ctx.tenant_id,
        phone_number_id=str(config.get("phone_number_id") or ""),
        sync_type=payload.sync_type,
        epoch=whatsapp_sync.epoch_for(config),
        note=payload.note,
    )
    return await whatsapp_coexistence_status(ctx)
