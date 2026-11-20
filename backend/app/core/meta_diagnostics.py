"""Meta channel diagnostics: every way linking or delivery can go wrong gets a NAME.

Until now a Meta failure was one of three things: an exception turned into a generic message,
a log line nobody reads, or nothing at all (a rejected webhook signature, a delivery for a page
no tenant owns). This module gives each failure a stable ``code`` and writes it to the
existing ``security_events`` trail (own transaction, never raises, tenant-scoped under RLS), so
the owner can read it through ``GET /platform/security-events?event_type=meta.<code>``.

Rules this file keeps:

* A code is a contract. Add to ``CATALOG``; never reuse a code for a different meaning.
* ``details`` carries ids, names, counts and Meta's own error fields (code, subcode, type,
  ``fbtrace_id``), never a token, a secret or a message body. Every value is redacted anyway.
* Recording a problem must never be the reason a request fails.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.log_redaction import redact

logger = logging.getLogger(__name__)

EVENT_PREFIX = "meta."

CHANNELS = ("whatsapp", "messenger", "instagram", "facebook")


@dataclass(frozen=True)
class Issue:
    """One named failure: how bad it is and what the owner should do about it."""

    severity: str  # critical | high | medium | low
    summary: str
    action: str


CATALOG: dict[str, Issue] = {
    # --- linking (OAuth / Embedded Signup) ---------------------------------------------------
    "link.code_exchange_failed": Issue(
        "high",
        "Meta refused the authorization code.",
        "Retry the connection. If it repeats, check the app id, the app secret and the redirect "
        "URI registered in Meta for developers.",
    ),
    "link.no_pages": Issue(
        "high",
        "Meta returned no Facebook Page for this account.",
        "Create or select a Page when Meta asks which assets to share, then connect again.",
    ),
    "link.no_instagram_account": Issue(
        "high",
        "The selected Page has no professional Instagram account linked.",
        "Link a Business or Creator Instagram account to this exact Page, then connect again.",
    ),
    "link.scopes_missing": Issue(
        "high",
        "Meta did not grant every permission the channel needs.",
        "Connect again and keep every permission switched on in Meta's dialog.",
    ),
    "link.page_choice_required": Issue(
        "low",
        "More than one Page was shared; the owner must choose one.",
        "Pick the Page in the dialog.",
    ),
    "link.subscription_failed": Issue(
        "critical",
        "The Page could not be subscribed to this app's webhooks, so nothing would arrive.",
        "Check the app's messaging permissions and that the account has full control of the Page.",
    ),
    "link.window_closed": Issue(
        "low",
        "The connect window closed before Meta's result reached the page.",
        "Connect again and keep the window open until it closes by itself.",
    ),
    "link.provider_unavailable": Issue(
        "medium",
        "Meta (or the path to it) was down or rate limiting while the channel was being linked.",
        "Nothing is wrong with the setup. Connect again in a minute.",
    ),
    "link.embedded_signup_rejected": Issue(
        "high",
        "WhatsApp Embedded Signup would not start or finish.",
        "Check the configuration id, the app's mode and the business portfolio's verification.",
    ),
    # --- tokens and permissions --------------------------------------------------------------
    "token.expired": Issue(
        "critical",
        "The channel's access token expired.",
        "Reconnect the channel to issue a fresh token.",
    ),
    "token.invalidated": Issue(
        "critical",
        "Meta invalidated the token (password change, session ended or app access removed).",
        "Reconnect the channel.",
    ),
    "token.refresh_failed": Issue(
        "high",
        "The scheduled token renewal failed.",
        "Reconnect before the current token runs out.",
    ),
    "permission.denied": Issue(
        "high",
        "Meta refused a call for a missing permission or an app-level restriction.",
        "Grant the permission in the connect dialog, or request it for the app in App Review.",
    ),
    # --- webhooks (inbound) ------------------------------------------------------------------
    "webhook.bad_signature": Issue(
        "critical",
        "A delivery arrived with a signature that does not match the app secret.",
        "The app secret stored here differs from the one in Meta. Update it, then resend a test.",
    ),
    "webhook.unknown_account": Issue(
        "high",
        "A delivery named an account that no store here owns.",
        "The account is not connected, or was disconnected while still subscribed in Meta.",
    ),
    "webhook.unparsable": Issue(
        "medium", "A delivery body could not be read as JSON.", "Resend from Meta's test tool."
    ),
    "webhook.verify_failed": Issue(
        "critical",
        "Meta's webhook verification request was refused.",
        "The verify token in Meta must equal the one configured on the server.",
    ),
    "webhook.silent": Issue(
        "high",
        "The channel is connected but no delivery has arrived for a long time.",
        "Check the webhook subscription and fields for this account in Meta.",
    ),
    "webhook.processing_failed": Issue(
        "high",
        "A delivery was stored but processing it failed.",
        "See the dead-letter queue; replay once the cause is fixed.",
    ),
    # --- sending (outbound) ------------------------------------------------------------------
    "send.rate_limited": Issue(
        "medium",
        "Meta throttled outgoing messages.",
        "Slow the send rate. A message Meta refused for this is not retried automatically: "
        "resend it from the conversation.",
    ),
    "send.window_closed": Issue(
        "medium",
        "The 24 hour reply window is closed for this contact.",
        "Use an approved template (WhatsApp) or a permitted message tag.",
    ),
    "send.recipient_unreachable": Issue(
        "medium",
        "Meta cannot deliver to this recipient.",
        "The contact may have blocked the account or not opted in.",
    ),
    "send.failed": Issue(
        "high", "Meta rejected an outgoing message.", "See the Meta error fields on this event."
    ),
    "send.media_failed": Issue(
        "medium", "An attachment could not be uploaded or fetched.", "Check type and size."
    ),
    # --- account state -----------------------------------------------------------------------
    "account.restricted": Issue(
        "critical",
        "Meta restricted or flagged this account or number.",
        "Open the account quality page in Meta; sending may be limited until it recovers.",
    ),
    "account.quality_dropped": Issue(
        "high",
        "The number's quality rating or messaging limit dropped.",
        "Reduce unsolicited messages and review blocked or reported conversations.",
    ),
    "api.unexpected": Issue(
        "medium",
        "Meta answered with an error this system does not classify yet.",
        "Send the Meta error fields to the developers.",
    ),
}


# (code, subcode) -> catalog key. ``None`` subcode matches any. Source: Meta Graph API error
# reference; only codes whose meaning is documented are mapped, the rest fall to api.unexpected.
_GRAPH_RULES: tuple[tuple[int, int | None, str], ...] = (
    (190, 463, "token.expired"),
    (190, 467, "token.invalidated"),
    (190, 460, "token.invalidated"),
    (190, 458, "token.invalidated"),
    (190, None, "token.invalidated"),
    (10, None, "permission.denied"),
    (200, None, "permission.denied"),
    (299, None, "permission.denied"),
    (4, None, "send.rate_limited"),
    (17, None, "send.rate_limited"),
    (32, None, "send.rate_limited"),
    (613, None, "send.rate_limited"),
    (80007, None, "send.rate_limited"),
    (130429, None, "send.rate_limited"),
    (368, None, "account.restricted"),
    (131031, None, "account.restricted"),
    (131047, None, "send.window_closed"),
    (131026, None, "send.recipient_unreachable"),
    (131030, None, "send.recipient_unreachable"),
    (131053, None, "send.media_failed"),
    (131052, None, "send.media_failed"),
)


def classify_graph_error(error: dict[str, Any] | None) -> str:
    """Catalog key for a Graph ``error`` object. Unknown shapes become ``api.unexpected``."""
    if not isinstance(error, dict):
        return "api.unexpected"
    code = error.get("code")
    subcode = error.get("error_subcode")
    for rule_code, rule_sub, key in _GRAPH_RULES:
        if code == rule_code and (rule_sub is None or subcode == rule_sub):
            return key
    return "api.unexpected"


def graph_error_fields(error: dict[str, Any] | None) -> dict[str, Any]:
    """The parts of a Graph error worth keeping. ``fbtrace_id`` is what Meta support asks for."""
    if not isinstance(error, dict):
        return {}
    keep = ("code", "error_subcode", "type", "fbtrace_id", "is_transient")
    fields: dict[str, Any] = {k: error[k] for k in keep if k in error}
    message = error.get("error_user_msg") or error.get("message")
    if message:
        fields["message"] = redact(str(message))[:300]
    return fields


def _clean(value: Any, depth: int = 0) -> Any:
    """Redact every string in a details payload; bounded so a huge body cannot ride along."""
    if isinstance(value, str):
        return redact(value)[:500]
    if isinstance(value, dict) and depth < 4:
        return {str(k)[:60]: _clean(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)) and depth < 4:
        return [_clean(v, depth + 1) for v in list(value)[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value))[:200]


def build_details(
    key: str, *, channel: str | None, details: dict[str, Any] | None
) -> dict[str, Any]:
    issue = CATALOG.get(key)
    body: dict[str, Any] = {
        "channel": channel,
        "severity": issue.severity if issue else "medium",
        "summary": issue.summary if issue else key,
        "action": issue.action if issue else "",
    }
    if details:
        body.update(_clean(details))
    return body


#: One database row per (key, channel, tenant) per window. A bad signature can be sent thousands of
#: times by anyone; the count lives in Redis, only the first of each window reaches the trail.
_DEDUPE_WINDOW_SECONDS = 300
_DEDUPE_LIMIT = 1
#: Used when Redis is unavailable: never more than this many rows per process per window.
_FALLBACK_BUDGET = 30
_fallback: dict[str, float] = {}


def _dedupe_key(key: str, channel: str | None, tenant_id: uuid.UUID | None) -> str:
    return f"meta_issue:{key}:{channel or '-'}:{tenant_id or '-'}"


async def _should_persist(key: str, channel: str | None, tenant_id: uuid.UUID | None) -> bool:
    """True for the first occurrence in the window (and a bounded trickle if Redis is down)."""
    import time

    name = _dedupe_key(key, channel, tenant_id)
    try:
        from app.core.ratelimit import FixedWindowLimiter
        from app.core.redis import get_redis_or_none

        client = get_redis_or_none()
        if client is not None:
            limiter = FixedWindowLimiter(
                client,
                limit=_DEDUPE_LIMIT,
                window_seconds=_DEDUPE_WINDOW_SECONDS,
                prefix="meta_issue_row",
            )
            return (await limiter.allow(name)).allowed
    except Exception:  # noqa: BLE001 - fall through to the in-process bound
        logger.debug("meta_diagnostics.dedupe_redis_unavailable", exc_info=True)
    now = time.monotonic()
    for stale in [k for k, t in _fallback.items() if now - t > _DEDUPE_WINDOW_SECONDS]:
        del _fallback[stale]
    if name in _fallback or len(_fallback) >= _FALLBACK_BUDGET:
        return False
    _fallback[name] = now
    return True


async def record_channel_issue(
    key: str,
    *,
    channel: str | None = None,
    tenant_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log and persist one named Meta problem. Never raises.

    ``key`` must be in ``CATALOG``; an unknown key is still recorded (so nothing is lost) but
    flagged, and the unit test that walks every call site keeps that from shipping.
    """
    if key not in CATALOG:
        logger.error("meta_diagnostics.unknown_key key=%s", key)
    body = build_details(key, channel=channel, details=details)
    logger.warning(
        "meta.issue key=%s channel=%s severity=%s tenant=%s details=%s",
        key,
        channel,
        body["severity"],
        tenant_id,
        {k: v for k, v in body.items() if k not in ("summary", "action")},
    )
    try:
        if not await _should_persist(key, channel, tenant_id):
            return
        from app.modules.platform.security_events import record_security_event

        await record_security_event(f"{EVENT_PREFIX}{key}", details=body, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001 - diagnostics must never break the flow they describe
        logger.warning("meta_diagnostics.write_failed key=%s", key, exc_info=True)
