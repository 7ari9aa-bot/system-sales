"""The shared linking layer: one Page connection, its capabilities, and the facts behind them.

A Meta Page is ONE object with several FIHRIST functions hanging off it (Facebook Page management,
Messenger messaging, Instagram messaging). The report's linking-layer findings were that the pieces
existed but nothing owned them together:

* the subscription's field set was computed in one place and merged in another, with no single
  owner and nothing stopping two requests from writing over each other;
* a reconnect could only ask for everything again, and could not tell a dead token from a missing
  webhook from an app-review refusal;
* backfill was Messenger-only, with no provider-agnostic shape;
* nothing documented which webhook events the system claims to handle, end to end.

This module is that owner. It reads an integration row and answers, in one object: which Page, which
capabilities, what was granted, what is subscribed, what state each capability is in, and — when
something is missing — exactly what to ask Meta for and why.

It does NOT merge the functions. Facebook Page management and Messenger stay separate capabilities
with separate permissions; they simply share the Page connection they hang off, which is what Meta
does too.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.modules.customers.capability_states import (
    ASSET_SUBSCRIPTION_MISSING,
    NEEDS_APP_REVIEW,
    NEEDS_CONNECTION,
    NEEDS_PERMISSION,
    TEMPORARY_FAILURE,
    evaluate,
)
from app.modules.customers.meta_channel_diagnostics import DASHBOARD_FIELDS

#: The FIHRIST functions that hang off one Page connection. Each has its own permission, and one
#: Page can have one without the other: a merchant may run the Page and not answer Messenger.
CAPABILITIES = ("facebook", "messenger", "instagram")

#: Which granted scope each function needs. Facebook Page management deliberately does NOT need
#: pages_messaging: reading and posting on a Page is not permission to answer its messages.
CAPABILITY_SCOPES: dict[str, tuple[str, ...]] = {
    "facebook": ("pages_manage_posts", "pages_read_engagement"),
    "messenger": ("pages_messaging",),
    "instagram": ("instagram_basic", "instagram_manage_messages"),
}

#: The webhook fields a capability needs subscribed, from the one map the diagnostics already use.
CAPABILITY_FIELDS: dict[str, tuple[str, ...]] = {
    "facebook": tuple(f for f in DASHBOARD_FIELDS["page"] if f in ("feed",)),
    "messenger": tuple(
        f
        for f in DASHBOARD_FIELDS["page"]
        if f
        in (
            "messages",
            "messaging_postbacks",
            "messaging_referrals",
            "message_echoes",
            "messaging_handovers",
            "message_edits",
            "message_reactions",
            "message_deliveries",
            "message_reads",
        )
    ),
    "instagram": tuple(DASHBOARD_FIELDS["instagram"]),
}


@dataclass(frozen=True)
class MetaPageConnection:
    """One Page as FIHRIST knows it, with every capability hanging off it.

    Built from an integration row by :meth:`from_integration`. Nothing here is a guess: a fact the
    caller did not measure stays ``None`` and is reported as unverified, never as a failure.
    """

    provider: str
    page_id: str | None
    asset_id: str | None
    status: str
    has_token: bool
    granted_scopes: frozenset[str] | None = None
    page_tasks: frozenset[str] | None = None
    subscribed_fields: frozenset[str] | None = None
    seen_fields: frozenset[str] = field(default_factory=frozenset)
    onboarding_mode: str | None = None

    @classmethod
    def from_integration(cls, integration: Any) -> MetaPageConnection:
        """Read an integration row into the connection shape, without inventing anything."""
        config = integration.config if isinstance(integration.config, dict) else {}
        connection = (
            config.get("_connection") if isinstance(config.get("_connection"), dict) else {}
        )
        scopes = connection.get("granted_scopes")
        tasks = connection.get("page_tasks")
        # The Page id lives in `page_id` for Facebook and in `account_id` for Messenger (the OAuth
        # callback writes only that). An Instagram or WhatsApp `account_id` is NOT a Page.
        provider = str(integration.provider)
        page_id = str(
            config.get("page_id") or (config.get("account_id") if provider == "messenger" else "")
        )
        # What actually arrived is recorded in `webhook_health["seen_fields"]` (a field -> time map
        # written by the webhook handler), never in `config`.
        health = getattr(integration, "webhook_health", None)
        health = health if isinstance(health, dict) else {}
        seen = health.get("seen_fields")
        return cls(
            provider=provider,
            page_id=page_id or None,
            asset_id=str(config.get("waba_id") or page_id or "") or None,
            status=str(integration.status),
            # Whether a token EXISTS is knowable here; its value never leaves the vault.
            has_token=bool(getattr(integration, "credentials", None)),
            granted_scopes=frozenset(scopes) if isinstance(scopes, list | tuple) else None,
            page_tasks=frozenset(tasks) if isinstance(tasks, list | tuple) else None,
            subscribed_fields=(
                frozenset(config["subscribed_fields"])
                if isinstance(config.get("subscribed_fields"), list | tuple)
                else None
            ),
            seen_fields=frozenset(str(k) for k in seen)
            if isinstance(seen, dict | list)
            else frozenset(),
            onboarding_mode=str(config.get("onboarding_mode") or "") or None,
        )

    @property
    def connected(self) -> bool:
        return self.status in ("active", "connected", "restricted")

    def capability_states(self) -> list[dict[str, Any]]:
        """One honest state per capability, from what was measured."""
        return evaluate(
            self.provider,
            connected=self.connected,
            granted_scopes=set(self.granted_scopes) if self.granted_scopes is not None else None,
            subscription_fields=(
                set(self.subscribed_fields) if self.subscribed_fields is not None else None
            ),
            seen_fields=set(self.seen_fields),
            subscription_known=self.subscribed_fields is not None,
        )

    def working_capabilities(self) -> tuple[str, ...]:
        """The functions that genuinely work right now (a state of `available`, nothing less)."""
        return tuple(row["key"] for row in self.capability_states() if row["state"] == "available")


def required_fields(capabilities: Iterable[str]) -> tuple[str, ...]:
    """The UNION of webhook fields the given capabilities need, in a stable order.

    A union, never an intersection: subscribing only what the newest capability wants would silently
    unsubscribe the older one, which is exactly the bug the report found in the subscription read.
    """
    wanted: list[str] = []
    for capability in capabilities:
        for name in CAPABILITY_FIELDS.get(capability, ()):
            if name not in wanted:
                wanted.append(name)
    return tuple(sorted(wanted))


def missing_scopes(capability: str, granted: Iterable[str] | None) -> tuple[str, ...]:
    """The scopes one capability still needs. ``None`` means "not measured": nothing is claimed."""
    if granted is None:
        return ()
    have = set(granted)
    return tuple(scope for scope in CAPABILITY_SCOPES.get(capability, ()) if scope not in have)


#: One lock per Page id. Two requests updating one Page's subscription at the same time is what
#: makes Meta answer with the field set of whichever arrived last, so updates are serialised per
#: Page, and different Pages never wait for each other.
_SUBSCRIPTION_LOCKS: dict[str, asyncio.Lock] = {}


def subscription_lock(page_id: str) -> asyncio.Lock:
    """The lock for one Page's subscription updates (created once, reused after that)."""
    lock = _SUBSCRIPTION_LOCKS.get(page_id)
    if lock is None:
        lock = asyncio.Lock()
        _SUBSCRIPTION_LOCKS[page_id] = lock
    return lock


async def lock_page_subscription(session: Any, page_id: str) -> None:
    """Serialise subscription changes for one Page across EVERY API instance.

    ``subscription_lock`` only orders requests inside one process; two instances behind a load
    balancer would still read, merge and write at the same time and the later POST would win. A
    Postgres transaction-level advisory lock is shared by all of them and is released by the commit
    or rollback that ends the link, so it can never be left held. A non-Postgres session (unit
    tests) has nothing to lock and is skipped.
    """
    from sqlalchemy import text

    bind = session.get_bind() if hasattr(session, "get_bind") else None
    if getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"meta_page_subscription:{page_id}"},
    )


class PageSubscriptionManager:
    """One owner for a Page's webhook subscription: compute, merge, never shrink by accident.

    The manager does not call Meta itself; it decides what should be asked for and what to do with
    an answer. That keeps the Graph calls in one place (`meta_oauth`) while the POLICY (union of
    fields, fail-safe read, per-Page serialisation) lives here.
    """

    def __init__(self, page_id: str) -> None:
        self.page_id = page_id
        self._lock = subscription_lock(page_id)

    def fields_for(self, capabilities: Iterable[str], *, keep: Iterable[str] = ()) -> list[str]:
        """What to subscribe: the union of the capabilities' fields PLUS anything already there.

        `keep` is the field set Meta reported. Keeping it is not politeness: a field this build does
        not know about (Meta adds them) must not be dropped because our list is shorter.
        """
        merged = list(required_fields(capabilities))
        for name in keep:
            if name not in merged:
                merged.append(name)
        return sorted(merged)

    def plan(
        self,
        capabilities: Iterable[str],
        *,
        current: Iterable[str] | None,
    ) -> dict[str, Any]:
        """What a subscription update would do, and whether it is needed at all.

        ``current is None`` means the read FAILED. In that case the plan is "do not write": writing
        a guessed set is how a failed GET turns into lost fields on the next POST.
        """
        caps = tuple(capabilities)
        wanted = self.fields_for(caps)
        if current is None:
            return {
                "write": False,
                "fields": wanted,
                "reason": "the current subscription could not be read; not overwriting it",
            }
        have = set(current)
        add = [name for name in wanted if name not in have]
        return {
            "write": bool(add),
            "fields": self.fields_for(caps, keep=have),
            "add": add,
            "reason": None if add else "every field the capabilities need is already subscribed",
        }

    async def apply(self, capabilities: Iterable[str], *, current: Iterable[str] | None, write):
        """Serialise one update per Page and hand the merged set to `write`.

        `write` is called with the merged field list, and only when something is actually missing:
        a no-op update still costs a Graph call and can race another one for nothing.
        """
        async with self._lock:
            plan = self.plan(capabilities, current=current)
            if not plan["write"]:
                return plan
            plan["result"] = await write(plan["fields"])
            return plan


# ---------- reconnect: ask only for what is missing, and say why ----------


def reconnect_plan(connection: MetaPageConnection, capability: str) -> dict[str, Any]:
    """What to ask Meta for to make ONE capability work, and what kind of failure is in the way.

    Four different problems look identical from a channel screen ("it does not work"), and they need
    four different answers:

    * ``no_connection`` — the channel is not linked at all;
    * ``token`` — there is a connection but no usable token: reconnect the account;
    * ``permission`` — the token is fine, the scope is missing: ask for that scope only;
    * ``webhook`` — the scope is granted, the field is not subscribed: fix the subscription;
    * ``app_review`` — Meta requires review or advanced access: nothing the merchant can do alone.
    """
    if not connection.connected:
        return {"action": "connect", "failure": NEEDS_CONNECTION, "scopes": (), "fields": ()}

    if not connection.has_token:
        return {
            "action": "reconnect_account",
            "failure": "token",
            "scopes": (),
            "fields": (),
            "reason": "the connection has no usable token; the account must be reconnected",
        }

    scopes = missing_scopes(capability, connection.granted_scopes)
    if scopes:
        return {
            "action": "request_scopes",
            "failure": NEEDS_PERMISSION,
            "scopes": scopes,
            "fields": (),
            "reason": "missing scopes: " + ", ".join(scopes),
        }

    if connection.subscribed_fields is None:
        return {
            "action": "fix_subscription",
            "failure": TEMPORARY_FAILURE,
            "scopes": (),
            "fields": required_fields((capability,)),
            "reason": "the subscription could not be read; re-check before writing",
        }

    lacking = [f for f in required_fields((capability,)) if f not in connection.subscribed_fields]
    if lacking:
        return {
            "action": "fix_subscription",
            "failure": ASSET_SUBSCRIPTION_MISSING,
            "scopes": (),
            "fields": tuple(lacking),
            "reason": "not subscribed: " + ", ".join(lacking),
        }

    unseen = [f for f in CAPABILITY_FIELDS.get(capability, ()) if f not in connection.seen_fields]
    if unseen:
        # Subscribed but never delivered: Meta is not sending it yet (review, or simply no event).
        return {
            "action": "wait_for_event",
            "failure": NEEDS_APP_REVIEW,
            "scopes": (),
            "fields": (),
            "reason": "subscribed but never delivered: "
            + ", ".join(unseen)
            + " (Meta may need review, or no such event has happened)",
        }

    return {"action": "none", "failure": None, "scopes": (), "fields": (), "reason": None}


# ---------- backfill: one shape, per-provider bounds ----------


@dataclass(frozen=True)
class BackfillBounds:
    """How far back one provider will walk, and how much it will take in one run.

    Meta rate-limits per Page and per app, so an unbounded backfill is a way to get the whole
    channel throttled. The bounds are per provider because Meta's own limits are.

    What these bounds buy is a LIMITED HISTORY IMPORT: the most recent conversations inside the
    caps, never a full sync. Anything that reads or labels a run must say so.
    """

    provider: str
    max_pages: int
    max_items: int
    max_days: int
    rate_limit_per_minute: int


BACKFILL_BOUNDS: dict[str, BackfillBounds] = {
    # Messenger's Conversation API: Meta documents a page size and a rate limit per Page.
    "messenger": BackfillBounds(
        "messenger", max_pages=5, max_items=100, max_days=90, rate_limit_per_minute=200
    ),
    # Instagram messaging is NOT walked by the Messenger walker (it reads a Page's conversations,
    # which an Instagram Login connection does not have), so reconcile reports it as unsupported.
    # These caps are for the comment list only, and Meta caps how far that goes.
    "instagram": BackfillBounds(
        "instagram", max_pages=3, max_items=50, max_days=30, rate_limit_per_minute=200
    ),
    # WhatsApp has no history API at all: that is a platform limit, not a missing job.
    "whatsapp": BackfillBounds(
        "whatsapp", max_pages=0, max_items=0, max_days=0, rate_limit_per_minute=0
    ),
}


def backfill_bounds(provider: str) -> BackfillBounds:
    """The bounds for a provider. An unknown provider gets the most conservative ones."""
    return BACKFILL_BOUNDS.get(
        provider,
        BackfillBounds(provider, max_pages=1, max_items=25, max_days=7, rate_limit_per_minute=60),
    )


def backfill_supported(provider: str) -> tuple[bool, str | None]:
    """Whether a provider can be backfilled at all, and why not when it cannot."""
    bounds = backfill_bounds(provider)
    if bounds.max_items == 0:
        return False, f"{provider} exposes no history API; nothing can be imported"
    return True, None


# ---------- the event registry ----------


@dataclass(frozen=True)
class EventSpec:
    """One webhook event as the system claims to handle it, stage by stage.

    ``persist`` and ``effect`` are the two that matter: an event that is parsed but not persisted
    (or persisted but with no domain effect) is the "silently ignored" bug the report kept finding.
    """

    object: str
    field_name: str
    classify: str
    persist: str
    effect: str
    diagnostic: str


EVENT_REGISTRY: tuple[EventSpec, ...] = (
    EventSpec("page", "messages", "inbound DM", "message row", "AI turn + realtime", "delivered"),
    EventSpec(
        "page",
        "message_echoes",
        "staff reply from Meta's inbox",
        "message row (deduped against our sends)",
        "conversation updated, no AI turn",
        "delivered",
    ),
    EventSpec(
        "page",
        "messaging_handovers",
        "thread control",
        "conversation ownership",
        "AI paused / resumed",
        "delivered",
    ),
    EventSpec(
        "page",
        "message_edits",
        "edited message",
        "existing message row (original kept)",
        "no AI turn",
        "delivered",
    ),
    EventSpec("page", "message_reactions", "reaction", "message reaction", "realtime", "delivered"),
    EventSpec(
        "page",
        "feed",
        "post/comment/mention/reaction",
        "page_activity row",
        "activity feed + local post refresh",
        "delivered",
    ),
    EventSpec(
        "instagram", "messages", "inbound DM", "message row", "AI turn + realtime", "delivered"
    ),
    # A hand-off between Meta apps reaches Instagram inside `messages` (message.admin_text), so it
    # has no webhook field of its own; Instagram's `messaging_handovers` does not exist.
    EventSpec(
        "instagram",
        "message_edit",
        "edited message",
        "message row (original kept)",
        "thread shows edited marker",
        "delivered",
    ),
    EventSpec(
        "instagram",
        "messaging_seen",
        "read receipt",
        "message status",
        "read ticks in the thread",
        "delivered",
    ),
    EventSpec(
        "instagram",
        "message_reactions",
        "reaction",
        "message reaction",
        "realtime",
        "delivered",
    ),
    EventSpec("instagram", "comments", "comment", "comment row", "comment inbox", "delivered"),
    EventSpec(
        "instagram", "live_comments", "live comment", "comment row", "comment inbox", "delivered"
    ),
    EventSpec(
        "instagram",
        "story_insights",
        "story metrics",
        "story insight row",
        "per-story view",
        "delivered",
    ),
    EventSpec(
        "whatsapp_business_account",
        "messages",
        "inbound message + statuses",
        "message row",
        "AI turn + delivery state",
        "delivered",
    ),
    EventSpec(
        "whatsapp_business_account",
        "account_update",
        "account restriction",
        "operational state",
        "owner notification",
        "delivered",
    ),
    EventSpec(
        "whatsapp_business_account",
        "phone_number_quality_update",
        "quality rating",
        "operational state",
        "owner notification",
        "delivered",
    ),
    EventSpec(
        "whatsapp_business_account",
        "message_template_status_update",
        "template review",
        "template row status",
        "template screen",
        "delivered",
    ),
)


def registry_rows() -> list[dict[str, str]]:
    """The registry as plain rows, for a doc or a screen."""
    return [
        {
            "object": spec.object,
            "field": spec.field_name,
            "classify": spec.classify,
            "persist": spec.persist,
            "effect": spec.effect,
            "diagnostic": spec.diagnostic,
        }
        for spec in EVENT_REGISTRY
    ]
