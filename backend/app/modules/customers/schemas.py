"""CUSTOMERS module pydantic contract — request bodies and response models.

Why this file exists (gap-register P8)
--------------------------------------
Every one of the 19 routes in ``router.py`` used to return a bare ``dict`` with
no ``response_model``, so the published OpenAPI document described ``{}`` for
the whole CRM surface: a generated client produced a contract with no fields,
and nothing on the server said what a route owes the caller. ``tests/
test_customers_http_surface.py`` pins the two halves — a model must be attached,
and the DOCUMENT must carry real properties.

Money (§47/ADR-053)
-------------------
``lifetime_value`` and the 360's order/payment aggregates are ``Decimal`` in
Python and cross JSON as ``str(Decimal)`` — the rule the ORDERS router already
ships for ``grand_total``/``amount`` (``"grand_total": str(o.grand_total)``),
and the rule ``tests/test_customer_money_wire.py`` proves for this column. The
payload builders keep doing that stringification; the fields below are typed
``str`` so the contract states it too. They are deliberately NOT ``float`` (a
twelve-figure amount loses its cent) and NOT ``Decimal`` (OpenAPI then says
``number | string``, which tells a client nothing about what actually arrives).

§146 redaction is why the PII columns are nullable
--------------------------------------------------
``_customer_summary`` and ``_redact_issue_item`` replace ``phone``/``email``
(and the phone columns the contact backfill renamed) with ``None`` for a caller
without ``pii:read``. A model that declared them ``str`` would raise while
serializing a refusal, turning a privacy rule into a 500.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- request bodies


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=31)
    email: str | None = Field(default=None, max_length=320)
    locale: str | None = Field(default=None, max_length=15)
    extra: dict | None = None


class ArchiveBody(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class MergeBody(BaseModel):
    source_customer_id: UUID
    target_customer_id: UUID


class TagBody(BaseModel):
    name: str = Field(min_length=1, max_length=63)


class NoteBody(BaseModel):
    body: str = Field(min_length=1)


class ContactIssueResolution(BaseModel):
    issue: str = Field(min_length=1, max_length=64)
    resolution: str = Field(min_length=1, max_length=32)
    # Only ``correct`` on a legacy-default issue uses it; everything else is
    # refused by the service, including any idea of merging here.
    phone: str | None = Field(default=None, max_length=31)


class IntegrationBody(BaseModel):
    provider: str = Field(max_length=63)
    kind: str = "channel"
    config: dict = {}
    credentials: dict = {}
    status: str = "connected"


class IntegrationConnectBody(BaseModel):
    """Credentials are accepted only by the server-side verifier."""

    provider: Literal["whatsapp", "instagram", "messenger", "telegram", "webchat"]
    credentials: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationDisconnectBody(BaseModel):
    """Explicit confirmation for ``POST /integrations/{id}/disconnect``.

    Disconnecting stops the tenant's inbound provider traffic, so the route
    refuses to run on a defaulted body: the caller must send ``confirm: true``.
    """

    confirm: bool = False


class IntegrationVerificationOut(BaseModel):
    id: UUID
    provider: str
    status: str
    credentials_verified: bool
    display_name: str | None = None
    verified_at: str | None = None
    public_key: str | None = None
    message: str | None = None


# -------------------------------------------------------------- list envelopes


class CustomerSummary(BaseModel):
    """The one customer shape the list, the PATCH echo and the merge echo share."""

    id: UUID
    name: str
    phone: str | None = None  # redacted (§146) without pii:read
    email: str | None = None
    lifetime_value: str = Field(
        description="str(Decimal) (§47/ADR-053) — never parse this as a float."
    )
    is_blocked: bool


class CustomerList(BaseModel):
    items: list[CustomerSummary]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque (created_at, id) keyset position; pass it back as "
        "`cursor`. The list sorts on that pair on EVERY page (P7).",
    )


class TagOut(BaseModel):
    id: UUID
    name: str
    color: str | None = None


class IdentityOut(BaseModel):
    id: UUID
    channel: str
    external_id: str


class AddressOut(BaseModel):
    id: UUID
    label: str | None = None
    line1: str
    line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    is_default: bool


class NoteOut(BaseModel):
    id: UUID
    body: str
    author_user_id: UUID | None = None
    created_at: str | None = None


class NoteCreated(BaseModel):
    """The POST echo carries what the write produced, nothing more."""

    id: UUID
    body: str


# -------------------------------------------------------------------- detail


class CustomerDetail(BaseModel):
    id: UUID
    name: str
    phone: str | None = None
    email: str | None = None
    locale: str | None = None
    version: int = Field(description="Row version — the If-Match/ETag token (G-15).")
    lifetime_value: str = Field(description="str(Decimal) (§47).")
    is_blocked: bool
    extra: dict
    deleted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    tags: list[TagOut]
    identities: list[IdentityOut]
    addresses: list[AddressOut]
    notes: list[NoteOut]


class BlockState(BaseModel):
    id: UUID
    is_blocked: bool


class Archived(BaseModel):
    id: UUID
    deleted_at: str = Field(description="§143 tombstone stamp (soft delete).")


# ------------------------------------------------- M12 contact quarantine (M12)


class ContactIssue(BaseModel):
    """One row the contact backfill could not fix on its own.

    Every key the server does not have comes back ``None``/empty rather than as
    a guess, and the phone-bearing columns are redactable: ``legacy_raw``,
    ``suspected_phone`` and ``canonical_phone`` are renamed phone numbers, so
    §146 covers them alongside ``phone`` (see ``_EXTRA_PHONE_FIELDS``).
    """

    customer_id: UUID
    name: str
    phone: str | None = None
    email: str | None = None
    phone_state: str = Field(description="One of core/contact_norm STATE_*.")
    issues: list[str]
    legacy_raw: str | None = None
    suspected_phone: str | None = None
    canonical_phone: str | None = None
    peer_customer_ids: list[str] = []


class ContactIssueList(BaseModel):
    items: list[ContactIssue]
    count: int = Field(description="Size of THIS page, capped by `limit`.")


# ------------------------------------------------------------- Customer 360


class Customer360Profile(BaseModel):
    id: UUID
    name: str
    phone: str | None = None
    email: str | None = None
    locale: str | None = None
    lifetime_value: str = Field(description="str(Decimal) (§47).")
    is_blocked: bool
    extra: dict
    deleted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class Customer360Order(BaseModel):
    id: UUID
    number: str
    status: str
    currency: str | None = None
    grand_total: str = Field(
        description="str(Decimal) — the ORDERS router ships the same column the same way (§47)."
    )
    channel: str | None = None
    placed_at: str | None = None
    created_at: str | None = None


class Customer360Conversation(BaseModel):
    """Pass-through of the §137 inbox read model, narrowed to this projection."""

    id: UUID
    channel: str
    status: str
    unread_count: int
    assignee_user_id: UUID | None = None
    last_message_at: str | None = None
    created_at: str | None = None


class Customer360Task(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str | None = None
    source: str | None = None
    assignee_user_id: UUID | None = None
    due_date: str | None = None
    created_at: str | None = None


class Customer360Payments(BaseModel):
    """Money actually collected, refunded and still owed — all amount strings."""

    currency: str
    orders_total: str
    paid_total: str
    refunded_total: str
    net_collected: str
    outstanding: str
    payment_count: int


class Customer360Stats(BaseModel):
    orders_shown: int
    conversations_shown: int
    tasks_shown: int
    open_tasks: int
    unread_messages: int
    event_count: int
    # Both money figures are always present: ``_payments`` returns them as
    # ``str(Decimal)`` on every path (a customer with no orders still gets
    # ``"0.00"``), so the stats projection copies them through unchanged. They
    # are typed ``str`` — required, not ``str | None`` — because §47 makes them
    # amounts that must never be read as a float, and a nullable amount would
    # publish ``number | string``-equivalent ``anyOf`` and lose the contract.
    net_collected: str = Field(description="str(Decimal) (§47); '0.00' when nothing collected.")
    outstanding: str = Field(description="str(Decimal) (§47); committed-not-yet-collected.")
    last_order_at: str | None = None
    last_message_at: str | None = None


class TimelineEntry(BaseModel):
    """One row of the merged stream; ``at`` is present by construction.

    Undated rows cannot be ordered, so the projection drops them — a nullable
    ``at`` here would mean a timeline entry the client cannot place.
    """

    kind: str
    at: str
    title: str | None = None
    subtitle: str | None = None
    ref_id: str | None = None
    meta: dict = {}


class Customer360(BaseModel):
    customer: Customer360Profile
    tags: list[TagOut]
    identities: list[IdentityOut]
    addresses: list[AddressOut]
    notes: list[NoteOut]
    orders: list[Customer360Order]
    conversations: list[Customer360Conversation]
    tasks: list[Customer360Task]
    payments: Customer360Payments
    stats: Customer360Stats
    timeline: list[TimelineEntry]


# ------------------------------------------------- platform routes in this file


class PlatformInvitation(BaseModel):
    id: UUID
    email: str
    role_code: str | None = None
    status: str


class IntegrationOut(BaseModel):
    id: UUID
    provider: str
    kind: str
    status: str
    credentials_verified: bool = False
    display_name: str | None = None
    verified_at: str | None = None
    webhook_status: str
    last_webhook_at: str | None = None
    webhook_url: str | None = None
    # The webchat/Telegram routing identifiers are public by design. Provider
    # credentials and all other configuration stay server-side.
    public_key: str | None = None


class IntegrationUpserted(BaseModel):
    id: UUID
    status: str


class MetaOAuthStartOut(BaseModel):
    """P8 contract for GET /integrations/meta/oauth/start: the ONLY field the
    frontend consumes is the Meta-owned dialog URL it navigates to."""

    authorize_url: str
