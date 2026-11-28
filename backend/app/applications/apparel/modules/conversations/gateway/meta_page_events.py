"""One Meta ``page`` webhook, routed to the capability each event belongs to.

Meta gives an app ONE callback URL per object type. A Facebook Page is a single ``page`` object
whose webhook carries two different kinds of news:

* ``entry[].messaging[]`` : private chat (messages, postbacks, referrals, receipts, echoes,
  reactions, thread-control handovers). This is Messenger.
* ``entry[].changes[]`` : the Page itself (``feed`` posts and comments, ``mention``). This is
  Facebook.

The platform has two channel records for that one Page (``messenger`` and ``facebook``), each with
its own settings and its own store link. Registering the callback on the Messenger path lost the
Facebook comments to the wrong channel, and registering it on the Facebook path did the reverse.
So there is a single ``/webhooks/meta/page`` callback and this router, which splits every entry
into the part for each capability, so the existing per-channel ingest sees exactly what it always
did. Nothing here talks to the database or to Meta; it only sorts a signed payload.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.core.config import get_settings

#: Capability -> the channel provider whose integration, adapter and settings handle it.
MESSENGER = "messenger"
FACEBOOK = "facebook"

#: ``changes[].field`` values that are the Page's own news. Anything else under ``changes`` is
#: still handed to Facebook (the comment parser ignores what it does not know) rather than lost.
FACEBOOK_FIELDS = frozenset({"feed", "mention", "ratings", "live_videos", "videos"})


def _entry_page_id(entry: dict) -> str:
    return str(entry.get("id") or "").strip()


def route_page_payload(payload: dict) -> dict[str, list[dict]]:
    """Split one signed ``page`` delivery into per-capability envelopes.

    Returns ``{"messenger": [...], "facebook": [...]}``: each list holds one envelope per Page
    (so a batch for two Pages still resolves each store on its own). An entry that carries both
    kinds of news contributes a ``messaging``-only copy to Messenger and a ``changes``-only copy
    to Facebook, so neither adapter sees the other's events and neither is parsed twice.
    """
    base = {k: v for k, v in payload.items() if k != "entry"}
    routed: dict[str, dict[str, list[dict]]] = {MESSENGER: {}, FACEBOOK: {}}

    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        page_id = _entry_page_id(entry)
        if not page_id:
            continue
        rest = {k: v for k, v in entry.items() if k not in ("messaging", "changes")}
        messaging = [e for e in entry.get("messaging", []) or [] if isinstance(e, dict)]
        changes = [c for c in entry.get("changes", []) or [] if isinstance(c, dict)]
        # Meta's standby channel (a secondary receiver) is chat too.
        standby = [e for e in entry.get("standby", []) or [] if isinstance(e, dict)]
        if messaging or standby:
            kept = {**rest}
            if messaging:
                kept["messaging"] = messaging
            if standby:
                kept["standby"] = standby
            routed[MESSENGER].setdefault(page_id, []).append(kept)
        if changes:
            routed[FACEBOOK].setdefault(page_id, []).append({**rest, "changes": changes})

    return {
        capability: [{**base, "entry": entries} for entries in by_page.values()]
        for capability, by_page in routed.items()
    }


def classify_entry(entry: dict) -> set[str]:
    """Which capabilities one entry carries news for (a diagnostic, not a router)."""
    found: set[str] = set()
    if entry.get("messaging") or entry.get("standby"):
        found.add(MESSENGER)
    if entry.get("changes"):
        found.add(FACEBOOK)
    return found


def event_kinds(payload: dict) -> dict[str, int]:
    """Count what a delivery contains, by kind, for the channel's diagnostics screen."""
    counts: dict[str, int] = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for event in entry.get("messaging", []) or []:
            if not isinstance(event, dict):
                continue
            for kind in (
                "message",
                "postback",
                "referral",
                "reaction",
                "delivery",
                "read",
                "pass_thread_control",
                "take_thread_control",
                "request_thread_control",
            ):
                if kind in event:
                    bump("echo" if (event.get("message") or {}).get("is_echo") else kind)
                    break
            else:
                bump("other")
        for change in entry.get("changes", []) or []:
            if isinstance(change, dict):
                bump(f"change:{change.get('field') or 'unknown'}")
    return counts


def check_page_signature(headers: dict[str, str], raw_body: bytes) -> bool:
    """``X-Hub-Signature-256`` for the page object, failing closed with no secret.

    The same rule Messenger and Facebook already used (``MESSENGER_APP_SECRET``, else the app's
    ``META_APP_SECRET``): one Meta app signs the page object, so there is one answer.
    """
    settings = get_settings()
    secret = settings.messenger_app_secret or getattr(settings, "meta_app_secret", "")
    if not secret:
        return False
    signature = headers.get("x-hub-signature-256", "")
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:].encode(), expected.encode())


def verify_page_request(query_params: dict[str, Any]) -> str | None:
    """Meta's subscribe handshake for the page callback (``hub.challenge``)."""
    expected = get_settings().messenger_verify_token
    if not expected:
        return None
    if (
        query_params.get("hub.mode") == "subscribe"
        and query_params.get("hub.verify_token") == expected
    ):
        return query_params.get("hub.challenge", "")
    return None
