"""What each channel capability actually is right now: one honest state per feature.

A channel screen needs one answer per button, not one per channel: "Inbox works, but a reply your
staff type in Meta's own inbox will not appear", "Mentions work", "Story insights cannot be read
because the field is not subscribed". Declaring a whole channel healthy because a message arrived is
the false green this module exists to prevent.

States are the audit's vocabulary, plus two the audit did not name:

* ``not_implemented`` — Meta supports the feature and this platform has not built it yet. Saying
  "not supported by API" here would blame Meta for our own gap.
* ``needs_connection`` — the channel is simply not linked.

Nothing here guesses: a state is derived only from facts the caller measured (granted scopes, the
asset subscription, the fields Meta has actually delivered) or from a declared constant.
"""

from __future__ import annotations

from typing import Any

AVAILABLE = "available"
NEEDS_PERMISSION = "needs_permission"
NEEDS_ADVANCED_ACCESS = "needs_advanced_access"
NEEDS_APP_REVIEW = "needs_app_review"
ACCOUNT_INELIGIBLE = "account_ineligible"
NOT_REQUESTED = "not_requested"
ELIGIBILITY_UNKNOWN = "eligibility_unknown"
REGION_RESTRICTED = "region_restricted"
UNSUPPORTED_BY_API = "unsupported_by_api"
NOT_IMPLEMENTED = "not_implemented"
NEEDS_CONNECTION = "needs_connection"
TEMPORARY_FAILURE = "temporary_failure"
NO_LIVE_EVENT_VERIFIED = "no_live_event_verified"
DASHBOARD_FIELD_MISSING = "dashboard_field_missing"
ASSET_SUBSCRIPTION_MISSING = "asset_subscription_missing"

#: Every state a capability can report, for a UI that must never show an unknown badge.
STATES = (
    AVAILABLE,
    NEEDS_PERMISSION,
    NEEDS_ADVANCED_ACCESS,
    NEEDS_APP_REVIEW,
    ACCOUNT_INELIGIBLE,
    NOT_REQUESTED,
    ELIGIBILITY_UNKNOWN,
    REGION_RESTRICTED,
    UNSUPPORTED_BY_API,
    NOT_IMPLEMENTED,
    NEEDS_CONNECTION,
    TEMPORARY_FAILURE,
    NO_LIVE_EVENT_VERIFIED,
    DASHBOARD_FIELD_MISSING,
    ASSET_SUBSCRIPTION_MISSING,
)

#: States that mean the capability genuinely works today.
WORKING = (AVAILABLE,)


#: A capability and what it needs. ``scopes`` are checked against what Meta says the token holds;
#: ``fields`` against the asset subscription; ``live_fields`` are the webhook fields that must have
#: delivered at least once before the feature can be called verified. ``blocked`` is a constant
#: statement about Meta or about us, so a dead button is explained instead of hidden.
def _roadmap_state(key: str) -> str:
    """The declared state of a Meta-gated WhatsApp feature (see whatsapp_roadmap)."""
    from app.applications.apparel.modules.customers.whatsapp_roadmap import ROADMAP

    return str(ROADMAP[key]["state"])


def _roadmap_reason(key: str) -> str:
    """Why that state, in Meta's terms, so a badge carries its evidence."""
    from app.applications.apparel.modules.customers.whatsapp_roadmap import ROADMAP

    spec = ROADMAP[key]
    return f"{spec['eligibility']} — {spec['evidence']}"


_CAPABILITIES: dict[str, tuple[dict[str, Any], ...]] = {
    "messenger": (
        {
            "key": "inbox",
            "scopes": ("pages_messaging",),
            "fields": ("messages",),
            "live_fields": ("messages",),
        },
        {
            "key": "staff_reply_sync",
            "scopes": ("pages_messaging",),
            "fields": ("message_echoes",),
            "live_fields": ("message_echoes",),
        },
        {
            "key": "handover",
            "scopes": ("pages_messaging",),
            "fields": ("messaging_handovers",),
            "live_fields": ("messaging_handovers",),
        },
        {
            "key": "message_edit",
            "scopes": ("pages_messaging",),
            "fields": ("message_edits",),
            # Message edits are quiet when idle: Meta only sends `message_edits` when
            # someone actually edits, so requiring it as a live field would make every
            # shop that never had an edit look broken.
            "live_fields": (),
            "quiet_when_idle": True,
        },
        {
            "key": "reactions",
            "scopes": ("pages_messaging",),
            "fields": ("message_reactions",),
            "live_fields": (),
        },
        # Platform settings (greeting, Get Started, persistent menu, ice breakers) and inbox
        # labels are WRITE calls, so they need no webhook field to be verified.
        {
            "key": "profile_settings",
            "scopes": ("pages_messaging",),
            "fields": (),
            "live_fields": (),
        },
        {"key": "inbox_labels", "scopes": ("pages_messaging",), "fields": (), "live_fields": ()},
        {
            "key": "conversation_history",
            "scopes": ("pages_messaging",),
            "fields": (),
            "live_fields": (),
        },
        # Measured on Meta's own page: Marketing Messages (Recurring Notifications) is deprecated
        # on 10 Feb 2026 and its successor API is closed to new integrations. Building an opt-in
        # flow now would ship a button Meta refuses, so the state says whose limit this is.
        {
            "key": "marketing_optin",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "blocked": UNSUPPORTED_BY_API,
            "blocked_reason": (
                "Meta deprecated Marketing Messages (Recurring Notifications) on 2026-02-10, "
                "and the replacement Marketing Messages API is limited to existing partners; "
                "no new opt-in flow can be created"
            ),
        },
    ),
    "facebook": (
        {"key": "posts", "scopes": ("pages_manage_posts",), "fields": ("feed",), "live_fields": ()},
        {
            "key": "comments",
            "scopes": ("pages_manage_engagement",),
            "fields": ("feed",),
            "live_fields": ("feed",),
        },
        {
            "key": "mentions",
            "scopes": ("pages_read_engagement",),
            "fields": ("mention",),
            "live_fields": (),
        },
        {"key": "insights", "scopes": ("read_insights",), "fields": (), "live_fields": ()},
        # The private reply to a commenter is a Messenger message sent by the Page. The Page
        # connection does not ask for `pages_messaging` (Messenger is its own function with its
        # own permission set), so this is reported as a permission the store can grant by linking
        # Messenger, not as a broken button.
        {"key": "private_reply", "scopes": ("pages_messaging",), "fields": (), "live_fields": ()},
    ),
    "instagram": (
        {
            "key": "direct",
            "scopes": ("instagram_business_manage_messages",),
            "fields": ("messages",),
            "live_fields": ("messages",),
        },
        {
            "key": "comments",
            "scopes": ("instagram_business_manage_comments",),
            "fields": ("comments",),
            "live_fields": ("comments",),
        },
        {
            "key": "mentions",
            "scopes": ("instagram_business_manage_comments",),
            "fields": ("mentions",),
            "live_fields": (),
        },
        # A hand-off between Meta apps reaches Instagram inside `messages` (`message.admin_text`),
        # so it is verified by the `messages` field and has no webhook field of its own.
        {
            "key": "handover",
            "scopes": ("instagram_business_manage_messages",),
            "fields": ("messages",),
            "live_fields": ("messages",),
        },
        {
            "key": "message_edit",
            "scopes": ("instagram_business_manage_messages",),
            "fields": ("message_edit",),
            "live_fields": (),
            "quiet_when_idle": True,
        },
        {
            "key": "reactions",
            "scopes": ("instagram_business_manage_messages",),
            "fields": ("message_reactions",),
            "live_fields": (),
            "quiet_when_idle": True,
        },
        {
            "key": "read_receipts",
            "scopes": ("instagram_business_manage_messages",),
            "fields": ("messaging_seen",),
            "live_fields": (),
            "quiet_when_idle": True,
        },
        # Meta only sends these while a broadcast is live / after a story ends, so a shop that
        # never goes live must not be told something is broken.
        {
            "key": "live_comments",
            "scopes": ("instagram_business_manage_comments",),
            "fields": ("live_comments",),
            "live_fields": (),
            "quiet_when_idle": True,
        },
        {
            "key": "story_insights",
            "scopes": ("instagram_manage_insights",),
            "fields": ("story_insights",),
            "live_fields": (),
            "quiet_when_idle": True,
        },
        {
            "key": "publishing",
            "scopes": ("instagram_business_content_publish",),
            "fields": (),
            "live_fields": (),
        },
        # Both are built (container + status poll + publish), so they are judged like any other
        # capability instead of being pinned to a stale "not built yet".
        {
            "key": "reels_publishing",
            "scopes": ("instagram_business_content_publish",),
            "fields": (),
            "live_fields": (),
        },
        {
            "key": "stories_publishing",
            "scopes": ("instagram_business_content_publish",),
            "fields": (),
            "live_fields": (),
        },
    ),
    "whatsapp": (
        {"key": "messages", "scopes": (), "fields": ("messages",), "live_fields": ("messages",)},
        {
            "key": "templates",
            "scopes": (),
            "fields": ("message_template_status_update",),
            "live_fields": (),
        },
        {"key": "account_alerts", "scopes": (), "fields": ("account_update",), "live_fields": ()},
        {
            "key": "number_quality",
            "scopes": (),
            "fields": ("phone_number_quality_update",),
            "live_fields": (),
        },
        # Built, but "built" is not "ready for this account": a Flow needs a published Flow on the
        # WABA and a catalog message needs a catalog linked to it. Without that fact the state is
        # unverified, never available.
        {
            "key": "flows",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "needs_fact": "flows_ready",
        },
        {
            "key": "catalog_messages",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "needs_fact": "catalog_ready",
        },
        # The four features Meta gates, declared from whatsapp_roadmap so the badge a screen shows
        # and the reason it shows are the same fact. `coexistence` used to be declared plain
        # AVAILABLE, which was a false green: nothing in signup handled the coexistence step at all.
        {
            "key": "coexistence",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "blocked": _roadmap_state("coexistence"),
            "blocked_reason": _roadmap_reason("coexistence"),
        },
        {
            "key": "calls",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "blocked": _roadmap_state("calls"),
            "blocked_reason": _roadmap_reason("calls"),
        },
        {
            "key": "groups",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "blocked": _roadmap_state("groups"),
            "blocked_reason": _roadmap_reason("groups"),
        },
        {
            "key": "marketing_messages",
            "scopes": (),
            "fields": (),
            "live_fields": (),
            "blocked": _roadmap_state("marketing_messages"),
            "blocked_reason": _roadmap_reason("marketing_messages"),
        },
    ),
}


def declared(provider: str) -> tuple[dict[str, Any], ...]:
    """The capabilities this platform knows about for a channel."""
    return _CAPABILITIES.get(provider, ())


def evaluate(
    provider: str,
    *,
    connected: bool,
    granted_scopes: set[str] | None = None,
    subscription_fields: set[str] | None = None,
    seen_fields: set[str] | None = None,
    subscription_known: bool = True,
    facts: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """One state per capability, from measured facts only.

    ``facts`` carries account-level readiness the webhook cannot show (``flows_ready``,
    ``catalog_ready``). A capability that declares ``needs_fact`` is available only when that fact
    is true; unknown reads as unverified, false as not set up.

    ``None`` for a fact means "not measured", which is reported as unverified rather than as a
    failure: an unreachable Graph must not look like a missing permission.
    """
    out: list[dict[str, Any]] = []
    for spec in declared(provider):
        state, reason = _state_for(
            spec,
            connected=connected,
            granted_scopes=granted_scopes,
            subscription_fields=subscription_fields,
            seen_fields=seen_fields,
            subscription_known=subscription_known,
            facts=facts,
        )
        entry = {"key": spec["key"], "state": state}
        if reason:
            entry["reason"] = reason
        out.append(entry)
    return out


def _state_for(
    spec: dict[str, Any],
    *,
    connected: bool,
    granted_scopes: set[str] | None,
    subscription_fields: set[str] | None,
    seen_fields: set[str] | None,
    subscription_known: bool,
    facts: dict[str, bool] | None = None,
) -> tuple[str, str | None]:
    blocked = spec.get("blocked")
    if blocked:
        return blocked, spec.get("blocked_reason")
    if not connected:
        return NEEDS_CONNECTION, None

    missing = [
        s for s in spec.get("scopes", ()) if granted_scopes is not None and s not in granted_scopes
    ]
    if missing:
        return NEEDS_PERMISSION, f"missing scopes: {', '.join(missing)}"

    if not subscription_known:
        return NO_LIVE_EVENT_VERIFIED, "the asset subscription could not be read"

    needed_fields = spec.get("fields", ())
    if needed_fields and subscription_fields is not None:
        lacking = [f for f in needed_fields if f not in subscription_fields]
        if lacking:
            return ASSET_SUBSCRIPTION_MISSING, f"not subscribed: {', '.join(lacking)}"

    live = spec.get("live_fields", ())
    if live:
        seen = seen_fields or set()
        unseen = [f for f in live if f not in seen]
        if unseen:
            return DASHBOARD_FIELD_MISSING, f"never delivered: {', '.join(unseen)}"

    needed_fact = spec.get("needs_fact")
    if needed_fact:
        known = facts or {}
        if needed_fact not in known:
            return NO_LIVE_EVENT_VERIFIED, f"not checked yet: {needed_fact}"
        if not known[needed_fact]:
            return NOT_REQUESTED, f"not set up on this account: {needed_fact}"

    return AVAILABLE, None
