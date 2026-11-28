"""Remove this app's webhook subscription on Meta when a channel is disconnected.

Disconnecting used to flip a row in our database and leave Meta still delivering the Page's or
the business account's events to us. This module does the other half.

Rules that matter:

* A Facebook Page is ONE subscription shared by the Messenger, Facebook and Instagram channels
  linked to it (the fields are merged on connect). Removing it while a sibling channel is still
  active would silence that sibling. So if a sibling on the same Page stays connected, the
  subscription is NARROWED to the sibling's own fields instead of deleted.
* A WhatsApp Business Account has its own subscription and is removed outright.
* Meta refusing, or being unreachable, never blocks the local disconnect. The outcome is kept in
  ``config["_meta_cleanup"]`` so it can be retried and shown, and a replayed disconnect does not
  call Meta twice once it has succeeded.

Nothing here touches the database or decrypts credentials: the caller passes plain values, so the
module adds no import edge to other modules and is tested against a mocked Graph.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.applications.apparel.modules.customers.meta_oauth import _GRAPH, subscribed_fields

#: The state kept on the integration row, under config["_meta_cleanup"].
DONE = "done"  # Meta confirmed the subscription is gone (or was already gone).
KEPT = "kept"  # A sibling channel on the same Page still needs it; it was narrowed instead.
PENDING = "pending"  # Meta could not be reached or refused; retry later.
NOT_NEEDED = "not_needed"  # Nothing was ever subscribed for this channel on Meta.

#: Providers whose webhook rides a Facebook Page subscription.
PAGE_PROVIDERS = ("messenger", "facebook", "instagram")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _record(state: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "at": _now(), **{k: v for k, v in extra.items() if v is not None}}


def _meta_error(response: httpx.Response) -> dict[str, Any]:
    """What Meta said, without anything secret: code, subcode and its text."""
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


#: Meta answers that mean "there is nothing left to remove". Retrying them would never help, so
#: they count as done: an expired or revoked token (190) and a Page or account that no longer
#: exists or that we no longer have access to (100 with subcode 33, 803) cannot receive our events
#: anyway.
_ALREADY_GONE_CODES = {190, 803}


def _is_already_gone(error: dict[str, Any]) -> bool:
    return error.get("code") in _ALREADY_GONE_CODES or (
        error.get("code") == 100 and error.get("subcode") == 33
    )


def sibling_fields(sibling_providers: list[str]) -> list[str]:
    """The merged field list the still-connected sibling channels need on the shared Page."""
    merged: list[str] = []
    for provider in sibling_providers:
        merged.extend(subscribed_fields(provider).split(","))
    return list(dict.fromkeys(merged))


async def unsubscribe_page(
    http: httpx.AsyncClient,
    *,
    page_id: str,
    page_token: str,
    sibling_providers: list[str],
) -> dict[str, Any]:
    """Remove (or narrow) this app's subscription on a Page. Never raises for a Meta refusal."""
    url = f"{_GRAPH}/{page_id}/subscribed_apps"
    try:
        if sibling_providers:
            # A sibling is still connected: keep the subscription, drop the fields only the
            # disconnected channel needed. Meta replaces the list on every POST.
            fields = sibling_fields(sibling_providers)
            response = await http.post(
                url, params={"subscribed_fields": ",".join(fields), "access_token": page_token}
            )
            kept = True
        else:
            response = await http.delete(url, params={"access_token": page_token})
            kept = False
    except httpx.RequestError:
        return _record(PENDING, reason="meta_unreachable")

    if response.is_success:
        try:
            ok = response.json().get("success") is True
        except (ValueError, AttributeError):
            ok = False
        if ok:
            return _record(KEPT if kept else DONE, siblings=sibling_providers or None)
    error = _meta_error(response)
    if _is_already_gone(error):
        return _record(DONE, reason="already_gone", meta=error)
    return _record(PENDING, reason="meta_refused", meta=error)


async def unsubscribe_waba(http: httpx.AsyncClient, *, waba_id: str, token: str) -> dict[str, Any]:
    """Remove this app's subscription from a WhatsApp Business Account."""
    try:
        response = await http.delete(
            f"{_GRAPH}/{waba_id}/subscribed_apps", headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.RequestError:
        return _record(PENDING, reason="meta_unreachable")
    if response.is_success:
        try:
            ok = response.json().get("success") is True
        except (ValueError, AttributeError):
            ok = False
        if ok:
            return _record(DONE)
    error = _meta_error(response)
    if _is_already_gone(error):
        return _record(DONE, reason="already_gone", meta=error)
    return _record(PENDING, reason="meta_refused", meta=error)


def needs_cleanup(config: object) -> bool:
    """True when Meta has not yet confirmed the removal (never tried, or it is pending)."""
    cleanup = config.get("_meta_cleanup") if isinstance(config, dict) else None
    if not isinstance(cleanup, dict):
        return True
    return cleanup.get("state") == PENDING
