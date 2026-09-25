"""PLATFORM module — pydantic response schemas for the HTTP surface.

Why these exist (``docs/GAP_REGISTER.md`` line P8)
-------------------------------------------------
``app/modules/platform/router.py`` answered every one of its 29 routes with a
hand-built ``dict``, and a route with no ``response_model`` contributes
``"schema": {}`` to the OpenAPI document — which is OpenAPI for "any JSON
anywhere". The document is what every client generator, the §115 contract audit
and the operators reading ``/openapi.json`` consume, so the module published 29
endpoints that described nothing.

The models below restate the shapes the handlers ALREADY emit. They add no
field, rename nothing and invent no value: a response model silently DROPS
undeclared keys, so an accurate mirror is the only safe edit. Where a field is
opaque on purpose (a metric's ``filters``, an ingress ``payload``, a §146
redacted ``details``) it stays an open JSON object rather than pretending to a
stricter contract than the server holds.

Money rule (§47/ADR-053) does not apply to any field here: platform carries no
amounts. Ordinary numbers (``attempts``, ``rollout_percent``, ``total``,
``version``) stay numbers on the wire, ids stay UUID strings and timestamps stay
ISO-8601 strings — exactly what the handlers emit.

The list envelope
-----------------
``{items: [...]}`` is the module's shape (five of its seven list routes already
spoke it), and a route that also accepts a page additionally carries
``total``/``limit``/``offset``, matching the pre-existing
``GET /platform/webhook-events``. The two exceptions are deliberate and are
documented at their routes: ``GET /platform/metrics/definitions`` carries the
registry-vs-row gap report next to its ``items`` (``missing``/``drifted`` are
the endpoint's whole point, not decoration), and ``GET /platform/health`` is a
status surface rather than a collection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

#: The page ceiling every paged platform list enforces. ``limit`` above this is
#: refused with a 422 rather than turned into a full-table read; ``LIMIT -1`` is
#: PostgreSQL for "no limit at all", so an unclamped negative is the exact
#: inverse of what the caller asked for.
PAGE_LIMIT_MAX = 200
PAGE_LIMIT_DEFAULT = 50

#: The §103 vocabulary. ``overall_health_status``/``integration_health`` are the
#: only producers and both are closed over these three values.
HealthStatus = Literal["healthy", "degraded", "down"]


# ---------------------------------------------------------------- flags (§76)


class FlagOut(BaseModel):
    """One ``feature_flags`` row — the tenant's rollout switch.

    A flag decides what to RENDER, never what to ALLOW (§76), which is why this
    payload carries no permission data.
    """

    feature: str
    enabled: bool
    workspace_id: uuid.UUID | None = None
    role_code: str | None = None
    rollout_percent: int = Field(ge=0, le=100)


class FlagListOut(BaseModel):
    """``GET /platform/flags``: every flag configured for the tenant."""

    items: list[FlagOut]


class FlagCheckOut(BaseModel):
    """``GET /platform/flags/{feature}/check``: the decision for THIS caller."""

    feature: str
    enabled: bool


# --------------------------------------------------------- metrics (§167)


class MetricSpecOut(BaseModel):
    """One in-code ``MetricSpec`` from the registry (the authority).

    No ``updated_at``: the registry is Python, not a row.
    """

    name: str
    definition: str
    source: str
    filters: dict[str, Any]
    timezone_rule: str
    currency_rule: str
    refund_treatment: str
    version: int


class MetricListOut(BaseModel):
    """``GET /platform/metrics``: the canonical registry."""

    items: list[MetricSpecOut]


class MetricDefinitionRowOut(BaseModel):
    """One ``metric_definitions`` ROW — the tenant's audit copy.

    Carries the superseded versions the registry physically cannot, hence its
    own model rather than a reuse of ``MetricSpecOut``.
    """

    name: str
    version: int
    definition: str
    source: str
    filters: dict[str, Any]
    timezone_rule: str
    currency_rule: str
    refund_treatment: str
    updated_at: datetime | None = None


class MetricDefinitionsOut(BaseModel):
    """``GET /platform/metrics/definitions``: rows + the convergence gap.

    ``missing`` and ``drifted`` are the reason this payload is not a plain
    ``{items}`` list: the two sources agree only when the seed/backfill actually
    reached this tenant, and the route reports the disagreement instead of
    hiding it.
    """

    items: list[MetricDefinitionRowOut]
    missing: list[str]
    drifted: list[str]


# ------------------------------------------------------- saved views (§95)


class SavedViewOut(BaseModel):
    """One saved list layout (filters/sort/columns/grouping/density)."""

    id: uuid.UUID
    name: str
    entity: str
    # stored verbatim and never interpreted server-side.
    definition: dict[str, Any]
    visibility: Literal["private", "team", "workspace"]
    owner_user_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SavedViewListOut(BaseModel):
    """A page of the views the caller may see."""

    items: list[SavedViewOut]
    total: int
    limit: int
    offset: int


class SavedViewDeletedOut(BaseModel):
    """The DELETE acknowledgement: the row is gone and says so."""

    id: uuid.UUID
    deleted: bool


# ---------------------------------------------------------- health (§103)


class IntegrationHealthOut(BaseModel):
    """One integration's rolled-up webhook status.

    Deliberately only ``provider`` + ``status``: ``webhook_health`` may carry a
    ``last_error`` string with a URL in it, and nothing like that leaves the
    health surface.
    """

    provider: str
    status: HealthStatus


class HealthSubsystemOut(BaseModel):
    """One subsystem row.

    ``detail`` is a short, non-sensitive description (fixed strings plus counts
    and ages). The route is declared ``response_model_exclude_none`` so an
    absent detail stays absent on the wire rather than turning into ``null``.
    """

    name: str
    status: HealthStatus
    detail: str | None = None
    integrations: list[IntegrationHealthOut] | None = None


class PlatformHealthOut(BaseModel):
    """``GET /platform/health``: worst status wins, plus the per-subsystem rows."""

    status: HealthStatus
    subsystems: list[HealthSubsystemOut]


# ------------------------------------------------------ admin plane (§160)


class TenantRowOut(BaseModel):
    """A tenant's METADATA — §160 forbids tenant data on this plane.

    No counts, no names-of-customers, nothing that reads a tenant's rows: a
    platform admin may see THAT a tenant exists, never WHAT is inside it.
    """

    id: uuid.UUID
    name: str
    lifecycle_state: str
    is_active: bool
    created_at: datetime | None = None


class TenantListOut(BaseModel):
    """A page of the deployment's tenants."""

    items: list[TenantRowOut]
    total: int
    limit: int
    offset: int


class TenantHealthOut(BaseModel):
    """The depth of a tenant's outbox backlog — a count, never a payload."""

    outbox_pending: int


class TenantDetailOut(BaseModel):
    """One tenant's metadata + health."""

    id: uuid.UUID
    name: str
    lifecycle_state: str
    is_active: bool
    status_reason: str | None = None
    created_at: datetime | None = None
    health: TenantHealthOut


class TenantStatusOut(BaseModel):
    """The after-image of a §48 lifecycle transition."""

    id: uuid.UUID
    lifecycle_state: str
    is_active: bool


# ------------------------------------------------- webhook DLQ (§24)


class WebhookEventOut(BaseModel):
    """One ingress row as the list shows it: enough to triage, no body.

    ``processing_status`` is the §24 vocabulary (pending / processing /
    processed / failed / dead / ignored / resolved) and stays open ``str``
    because a worker writes it, not this route — a value the reader has never
    seen must render, not fail the response.
    """

    id: uuid.UUID
    provider: str
    external_event_id: str | None = None
    tenant_id: uuid.UUID | None = None
    received_at: datetime | None = None
    signature_valid: bool
    processing_status: str
    attempts: int
    last_error: str | None = None
    processed_at: datetime | None = None


class WebhookEventListOut(BaseModel):
    """``GET /platform/webhook-events``: a page of the ingress ledger."""

    total: int
    limit: int
    offset: int
    items: list[WebhookEventOut]


class WebhookEventDetailOut(WebhookEventOut):
    """The full row: the summary plus the raw payload.

    The body is the provider's document — an object for every channel the
    platform ingests today, and typed to accept an array as well so a row that
    physically holds one (JSONB) renders instead of failing validation.
    """

    payload: dict[str, Any] | list[Any]


class WebhookRetryOut(BaseModel):
    """The staged replay: the row, its tenant and what was scheduled."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    retry: str


class WebhookCloseOut(BaseModel):
    """An ignore/resolve close-out. The row never disappears (§24)."""

    id: uuid.UUID
    status: str


# ------------------------------------------------- break-glass (§147)


class BreakGlassOut(BaseModel):
    """The one-shot capability token.

    This is the only response in the module that carries a credential, and it
    carries it exactly once: the token is minted here and consumed by the
    protected action (GETDEL), so there is no later read to model.
    """

    capability_token: str
    expires_in_minutes: int


class BreakGlassValidateOut(BaseModel):
    """The pre-flight answer. A check must not burn the token."""

    valid: bool


# ------------------------------------------------------- secrets (§68-69)


class SecretReferenceOut(BaseModel):
    """A secret REFERENCE, never a value (§68).

    The value lives in the ``SecretStorePort`` and leaves only through it; this
    row is the pointer, its version and whether it is usable.
    """

    id: uuid.UUID
    provider: str
    scope: str
    vault_key: str
    version: int
    status: str


class SecretRotatedOut(BaseModel):
    """The new version after a §69 rotation (the old one stays for the grace period)."""

    id: uuid.UUID
    provider: str
    version: int
    rotated_at: datetime | None = None
    status: str


# ----------------------------------------------- tenant restore (§164)


class TenantRestoreJobOut(BaseModel):
    """A restore job and its three manifests.

    The manifests are ``{entity_type: {...}}`` maps written by the service
    (extraction counts and ids, validation conflicts, restore outcomes), so
    they stay open objects rather than a schema the server does not pin.
    """

    id: uuid.UUID
    target_tenant_id: uuid.UUID
    backup_point: datetime | None = None
    entity_types: list[str]
    status: str
    extraction_results: dict[str, Any] | None = None
    validation_results: dict[str, Any] | None = None
    restore_results: dict[str, Any] | None = None
    last_error: str | None = None
    completed_at: datetime | None = None


# ------------------------------------------------ security events (§67)


class SecurityEventOut(BaseModel):
    """One row of the §67 trail.

    ``details`` is the §146-redacted map: PII keys nulled without ``pii:read``,
    secret keys ALWAYS — which is why it is an open object whose values are
    ``Any`` (a nulled key legitimately arrives as ``null``).
    """

    id: uuid.UUID
    event_type: str
    actor_user_id: uuid.UUID | None = None
    ip: str | None = None
    details: dict[str, Any]
    created_at: datetime | None = None


class SecurityEventListOut(BaseModel):
    """A page of the caller's tenant trail, newest first."""

    items: list[SecurityEventOut]
    total: int
    limit: int
    offset: int
