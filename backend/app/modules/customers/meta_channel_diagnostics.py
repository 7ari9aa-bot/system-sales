"""A per-channel health report for a Meta channel: what works, what does not, and what to do.

A channel can read "connected" while no message ever arrives: the login worked, but the app-level
webhook was never set in the Meta dashboard, a field was left unticked, or the Page was never
subscribed. Each of those is a separate fact with a separate fix, so each is a separate check here.

Two parts:

* ``probe_*`` ask Meta (Graph) what is true right now. They never raise: a Meta outage or a refused
  token is the answer ``unknown``/``error`` for that check, never a failed request.
* ``build_report`` turns what was learned plus our own records (scopes granted, the last webhook,
  the last failure) into the list of checks. It is pure, so every rule is a unit test.

No token or secret ever appears in a report. Meta's own error code and text do, because that is
what support needs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.modules.customers.meta_oauth import _GRAPH, subscribed_fields
from app.modules.customers.meta_scopes import (
    FACEBOOK_PAGE_SCOPES,
    INSTAGRAM_REQUIRED_SCOPES,
    MESSENGER_SCOPES,
)

OK = "ok"
WARNING = "warning"
ERROR = "error"
UNKNOWN = "unknown"

#: The Meta object each channel's events arrive on, and the callback path the owner must register
#: for it in the App Dashboard. A Page serves Messenger AND Facebook on one callback.
WEBHOOK_OBJECT = {
    "messenger": ("page", "/api/v1/webhooks/meta/page"),
    "facebook": ("page", "/api/v1/webhooks/meta/page"),
    "instagram": ("instagram", "/api/v1/webhooks/instagram"),
    "whatsapp": ("whatsapp_business_account", "/api/v1/webhooks/whatsapp"),
}

#: What the app-level (dashboard) subscription must tick, per object. Meta delivers a field only
#: when it is subscribed at BOTH levels: on the app for the object, and on the asset.
DASHBOARD_FIELDS = {
    "page": (
        "messages",
        "messaging_postbacks",
        "messaging_referrals",
        "message_deliveries",
        "message_reads",
        "message_reactions",
        "feed",
    ),
    "instagram": ("messages", "messaging_postbacks", "comments"),
    "whatsapp_business_account": ("messages",),
}

#: Past this long without any webhook a connected channel is worth a second look. A quiet shop is
#: not a broken one, so it is a warning and only after the channel has been connected that long.
QUIET_AFTER = timedelta(days=3)


def _check(
    key: str, status: str, summary: str, action: str | None = None, **detail: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {"key": key, "status": status, "summary": summary}
    if action:
        out["action"] = action
    clean = {k: v for k, v in detail.items() if v not in (None, [], {})}
    if clean:
        out["detail"] = clean
    return out


# --------------------------------------------------------------------------- Graph probes


def _meta_error(response: httpx.Response) -> dict[str, Any]:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    return {
        "http_status": response.status_code,
        "code": error.get("code"),
        "subcode": error.get("error_subcode"),
        "message": str(error.get("message") or "")[:200] or None,
    }


async def probe_subscription(
    http: httpx.AsyncClient, *, asset_id: str, token: str, app_id: str | None
) -> dict[str, Any]:
    """Is OUR app subscribed on this Page / business account, and to which fields?

    ``{"state": "ok", "fields": [...]}``, ``{"state": "missing"}`` (reachable, but our app is not
    in the list), or ``{"state": "error"|"unknown", ...}`` when Meta could not answer.
    """
    try:
        response = await http.get(
            f"{_GRAPH}/{asset_id}/subscribed_apps", headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.RequestError:
        return {"state": UNKNOWN, "reason": "meta_unreachable"}
    if not response.is_success:
        return {"state": ERROR, "meta": _meta_error(response)}
    try:
        rows = response.json().get("data") or []
    except (ValueError, AttributeError):
        return {"state": UNKNOWN, "reason": "unreadable_answer"}
    rows = [r for r in rows if isinstance(r, dict)]
    mine = [r for r in rows if app_id and str(r.get("id")) == str(app_id)] or (
        # No app id configured here: a Page normally lists only apps we can see; take the first.
        rows[:1] if not app_id else []
    )
    if not mine:
        return {"state": "missing", "apps_listed": len(rows)}
    fields: list[str] = []
    for row in mine:
        raw = row.get("subscribed_fields")
        if isinstance(raw, list):
            fields.extend(str(f) for f in raw)
    return {"state": OK, "fields": sorted(set(fields))}


async def probe_permissions(http: httpx.AsyncClient, *, token: str) -> dict[str, Any]:
    """The permissions Meta says this token holds right now (not what we recorded at link time)."""
    try:
        response = await http.get(
            f"{_GRAPH}/me/permissions", headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.RequestError:
        return {"state": UNKNOWN, "reason": "meta_unreachable"}
    if not response.is_success:
        return {"state": ERROR, "meta": _meta_error(response)}
    try:
        rows = response.json().get("data") or []
    except (ValueError, AttributeError):
        return {"state": UNKNOWN, "reason": "unreadable_answer"}
    granted = sorted(
        str(r["permission"])
        for r in rows
        if isinstance(r, dict) and r.get("status") == "granted" and r.get("permission")
    )
    return {"state": OK, "granted": granted}


# --------------------------------------------------------------------------- the report


def _required_scopes(provider: str) -> tuple[str, ...]:
    if provider == "facebook":
        return tuple(MESSENGER_SCOPES.split(",")) + tuple(FACEBOOK_PAGE_SCOPES)
    if provider == "instagram":
        return tuple(INSTAGRAM_REQUIRED_SCOPES) + ("pages_messaging",)
    if provider == "messenger":
        return tuple(MESSENGER_SCOPES.split(","))
    return ()  # WhatsApp access is by business account, not by Page permission


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def build_report(
    *,
    provider: str,
    status: str,
    config: dict | None,
    webhook_health: dict | None,
    recorded_scopes: list[str] | None,
    subscription: dict | None,
    permissions: dict | None,
    server_webhook_ready: bool,
    api_base_url: str | None,
    failed_events: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The checks for one channel, in the order an owner would fix them.

    ``subscription`` and ``permissions`` are the probe answers (``None`` = not probed, for a
    channel that is not connected). The overall ``state`` is the worst check, so a screen can show
    one badge and the list underneath.
    """
    now = now or datetime.now(UTC)
    health = webhook_health if isinstance(webhook_health, dict) else {}
    obj, path = WEBHOOK_OBJECT.get(provider, ("", ""))
    callback = f"{api_base_url.rstrip('/')}{path}" if api_base_url and path else path or None
    checks: list[dict[str, Any]] = []

    # 1. Is the channel connected at all?
    connected = status in ("active", "connected", "restricted")
    if status == "reauth_required":
        checks.append(
            _check(
                "connection",
                ERROR,
                "Meta no longer accepts this connection (the login expired or was revoked).",
                "Connect the channel again and approve every permission.",
            )
        )
    elif status == "restricted":
        checks.append(
            _check(
                "connection",
                WARNING,
                "Meta has restricted this account.",
                "Open the account in Meta Business Suite and resolve the restriction.",
            )
        )
    elif not connected:
        checks.append(
            _check(
                "connection",
                ERROR,
                "This channel is not connected.",
                "Connect it from the channels settings.",
            )
        )
    else:
        checks.append(_check("connection", OK, "The channel is connected."))

    # 2. Permissions: what Meta says the token holds now, falling back to what we recorded.
    required = _required_scopes(provider)
    if required:
        live = permissions if isinstance(permissions, dict) else None
        if live and live.get("state") == OK:
            have, source = set(live.get("granted") or []), "meta"
        elif recorded_scopes is not None:
            have, source = set(recorded_scopes), "recorded"
        else:
            have, source = None, None
        if have is None:
            checks.append(
                _check("permissions", UNKNOWN, "The granted permissions could not be read.")
            )
        else:
            missing = [s for s in required if s not in have]
            if missing:
                checks.append(
                    _check(
                        "permissions",
                        ERROR if "pages_messaging" in missing else WARNING,
                        "Meta did not grant every permission this channel needs.",
                        "Connect again and keep every permission switched on in Meta's dialog.",
                        missing=missing,
                        source=source,
                    )
                )
            else:
                checks.append(_check("permissions", OK, "Every needed permission is granted."))

    # 3. Server side: can we answer Meta's handshake and verify its signature at all?
    if not server_webhook_ready:
        checks.append(
            _check(
                "server_webhook",
                ERROR,
                "This server cannot accept Meta's webhook yet (a secret or verify token, or the "
                "public API address, is not set).",
                "Set the Meta app secret, the verify token and the public API URL on the server.",
            )
        )
    else:
        checks.append(_check("server_webhook", OK, "The server can verify Meta's webhook."))

    # 4. The asset (Page / business account) subscription, asked of Meta live.
    wanted = subscribed_fields(provider).split(",") if provider != "whatsapp" else ["messages"]
    if subscription is None:
        pass
    elif subscription.get("state") == OK:
        have_fields = set(subscription.get("fields") or [])
        lacking = [f for f in wanted if f not in have_fields]
        if lacking:
            checks.append(
                _check(
                    "asset_subscription",
                    WARNING,
                    "Our app is subscribed, but not to every field this channel needs.",
                    "Disconnect and connect the channel again so the fields are re-subscribed.",
                    missing_fields=lacking,
                    subscribed_fields=sorted(have_fields),
                )
            )
        else:
            checks.append(
                _check(
                    "asset_subscription",
                    OK,
                    "The Page is subscribed to this app."
                    if provider != "whatsapp"
                    else "The business account is subscribed to this app.",
                    subscribed_fields=sorted(have_fields),
                )
            )
    elif subscription.get("state") == "missing":
        checks.append(
            _check(
                "asset_subscription",
                ERROR,
                "Meta does not list this app as subscribed, so no event reaches us.",
                "Connect the channel again; it subscribes the Page or business account.",
            )
        )
    elif subscription.get("state") == ERROR:
        checks.append(
            _check(
                "asset_subscription",
                ERROR,
                "Meta refused to tell us whether the app is subscribed.",
                "Connect the channel again; if it repeats, send the Meta code to support.",
                meta=subscription.get("meta"),
            )
        )
    else:
        checks.append(
            _check("asset_subscription", UNKNOWN, "Meta could not be reached to check this.")
        )

    # 5. The app-level subscription lives in the Meta dashboard and cannot be read with a Page
    #    token. We can only say what must be there, and infer it from traffic.
    if obj:
        last_seen = _parse_time(health.get("last_webhook_at"))
        if last_seen is not None:
            checks.append(
                _check(
                    "dashboard_webhook",
                    OK,
                    "Meta has delivered events to this server, so the dashboard webhook works.",
                    last_webhook_at=last_seen.isoformat(),
                )
            )
        elif connected:
            checks.append(
                _check(
                    "dashboard_webhook",
                    WARNING,
                    "No event has ever arrived. The webhook may not be set in the Meta app "
                    "dashboard (it cannot be checked from here).",
                    f"In the Meta app dashboard, set the callback URL for the {obj} object and "
                    f"tick: {', '.join(DASHBOARD_FIELDS.get(obj, ()))}. Then send a test message.",
                    callback_url=callback,
                    object=obj,
                    fields=list(DASHBOARD_FIELDS.get(obj, ())),
                )
            )

    # 6. Recent delivery trouble.
    failures = int(health.get("consecutive_failures") or 0)
    if failures or failed_events:
        checks.append(
            _check(
                "recent_failures",
                ERROR if failures >= 3 else WARNING,
                "Some events reached us but could not be processed.",
                "Send the error below to support; failed events are kept and can be replayed.",
                consecutive_failures=failures or None,
                failed_events=failed_events or None,
                last_error=health.get("last_error"),
                last_failure_at=health.get("last_failure_at"),
            )
        )
    elif connected:
        last_seen = _parse_time(health.get("last_webhook_at"))
        if last_seen is not None and now - last_seen > QUIET_AFTER:
            checks.append(
                _check(
                    "recent_activity",
                    WARNING,
                    f"No event for {(now - last_seen).days} days.",
                    "If customers are writing, check the dashboard webhook and the subscription.",
                    last_webhook_at=last_seen.isoformat(),
                )
            )

    order = {ERROR: 3, WARNING: 2, UNKNOWN: 1, OK: 0}
    worst = max((c["status"] for c in checks), key=lambda s: order[s], default=OK)
    return {
        "provider": provider,
        "state": worst,
        "webhook_object": obj or None,
        "callback_url": callback,
        "last_webhook_at": health.get("last_webhook_at"),
        "checks": checks,
    }
