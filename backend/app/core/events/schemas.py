"""Typed event envelopes for the bus.

Envelopes add a stable schema (version, type, tenant, aggregate identity) on
top of the transport's opaque payload/meta split (see app.core.events.bus).
Domain modules register an envelope subclass under their event type name and
construct instances via build_envelope(); serialize() / deserialize() map to
and from the Redis Streams field layout used by the bus (payload + meta).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.errors import ValidationError

EVENT_TYPES: dict[str, type[EventEnvelope]] = {}

# §153: schema_version-specific adapters. A consumer that understands an
# evolved payload registers its subclass under (event_type, schema_version);
# ``build_envelope`` / ``deserialize`` pick the adapter when one exists for
# the event's own version and fall back to the type-level class otherwise —
# so an old event stays readable through the base contract.
VERSIONED_EVENT_TYPES: dict[tuple[str, int], type[EventEnvelope]] = {}

# Meta keys that carry envelope routing rather than user-supplied metadata.
ROUTING_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "type",
        "version",
        "tenant_id",
        "workspace_id",
        "location_id",
        "occurred_at",
        "aggregate_type",
        "aggregate_id",
        "correlation_id",
        "causation_id",
        "producer",
        "schema_version",
        "aggregate_version",
        "decision_id",
        "effect_id",
    }
)


def register_event(
    name: str, schema_version: int | None = None
) -> Callable[[type[EventEnvelope]], type[EventEnvelope]]:
    """Register an envelope class under an event type name (e.g. "order.created").

    With ``schema_version`` the class is registered as the §153 adapter for
    that wire version only; without it, the class is the type-level contract.
    Re-registering the same class under the same key is a no-op; a different
    class for a taken key is a programming error and raises ValueError.
    """

    def decorator(cls: type[EventEnvelope]) -> type[EventEnvelope]:
        if schema_version is not None:
            key = (name, schema_version)
            existing = VERSIONED_EVENT_TYPES.get(key)
            if existing is not None and existing is not cls:
                raise ValueError(
                    f"event adapter already registered: {name!r} @ v{schema_version}"
                    f" -> {existing.__name__}"
                )
            VERSIONED_EVENT_TYPES[key] = cls
            return cls
        existing = EVENT_TYPES.get(name)
        if existing is not None and existing is not cls:
            raise ValueError(f"event type already registered: {name!r} -> {existing.__name__}")
        EVENT_TYPES[name] = cls
        return cls

    return decorator


class EventEnvelope(BaseModel):
    """Envelope stamped onto every bus message.

    Subclasses narrow ``payload`` (and optionally ``meta``) to typed pydantic
    models; the base keeps them as free-form dicts.
    """

    version: int = 1
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    tenant_id: UUID
    # §19 scope: the sub-tenant ownership the event happened under. Optional
    # until a mutation resolves a workspace/location scope (§151); routing
    # keys, so user meta can never forge them.
    workspace_id: UUID | None = None
    location_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    # envelope v2 lineage fields — all optional with defaults so v1 callers
    # (and subclasses that only narrow payload/meta) keep working unchanged.
    correlation_id: str | None = None
    causation_id: str | None = None
    producer: str = "core"
    schema_version: int = 1
    aggregate_version: int | None = None
    decision_id: UUID | None = None
    effect_id: UUID | None = None


# The closed set of event types the outbox actually publishes. Every entry is a
# real add_outbox_event(..., event_type=...) call site in app/ — none invented.
# They all use the free-form base envelope because no domain module narrows
# payload/meta yet; a module that adds a typed subclass must register it BEFORE
# this import runs (or replace the base registration) — see register_event.
DOMAIN_EVENT_TYPES: tuple[str, ...] = (
    # §169: AI evaluation canary rollout lifecycle (ai/evaluation.py).
    "ai.canary_rolled_back",
    "ai.canary_started",
    # §136: per-tenant n8n service-token lifecycle (issue / rotate / revoke).
    "automation.service_token.issued",
    "automation.service_token.revoked",
    # §175: campaign + journey execution lifecycle (marketing/). The
    # campaign.run.batch continuation is staged by the CampaignWorker with a
    # pacing not_before (§144 bulk tier).
    "campaign.run.batch",
    "campaign.run.completed",
    "campaign.run.started",
    "customer.merged",
    "journey.run.completed",
    "journey.run.started",
    "message.outbound",
    "message.received",
    "notification.queued",
    "order.cancelled",
    "order.created",
    "order.refunded",
    "order.shipping_updated",
    "order.status_changed",
    # §69: master-key rotation emits this through the outbox (durable audit of
    # a security-relevant event — see app.core.secrets.rotate_master_key).
    "platform.secret_rotated",
    "privacy.customer_deleted",
    "privacy.customer_purge_required",
    # §126: saga orchestration milestones (core/saga.py).
    "saga.completed",
    "saga.failed",
    "saga.started",
    # §164: tenant-scoped restore job lifecycle (create → extract → validate
    # → execute) stages these from platform/tenant_restore.py.
    "tenant.restore.completed",
    "tenant.restore.requested",
    "webhook.deliver",
    # §24: failed inbound webhook ingress rows are reprocessed by the
    # WebhookWorker (admin retry endpoint / per-tenant sweep) on the same
    # webhook.events stream.
    "webhook.event.retry",
    # §22: the webhook route persists the raw delivery and queues the long
    # ingest block onto this event — the request path never runs it inline.
    "webhook.ingest",
    # §176 gate-scenario fixtures (relay reclaim, redis-outage buffering,
    # schema-version round-trip) stage real envelopes through the writer.
    "test.relay",
    "test.redis_out",
    "test.schema",
)


def _register_domain_event_types() -> None:
    for name in DOMAIN_EVENT_TYPES:
        register_event(name)(EventEnvelope)


_register_domain_event_types()


def _resolve_class(event_type: str, schema_version: int) -> type[EventEnvelope] | None:
    """§153 dispatch: the adapter registered for this exact wire version, else
    the type-level class. An unregistered type resolves to None (rejected)."""
    return VERSIONED_EVENT_TYPES.get((event_type, schema_version)) or EVENT_TYPES.get(event_type)


def build_envelope(
    event_type: str,
    *,
    tenant_id: UUID | str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    workspace_id: UUID | str | None = None,
    location_id: UUID | str | None = None,
    payload: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    envelope_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    producer: str = "core",
    schema_version: int = 1,
    aggregate_version: int | None = None,
    decision_id: UUID | str | None = None,
    effect_id: UUID | str | None = None,
) -> EventEnvelope:
    """Build a registered envelope; unknown event types are rejected.

    The v2 lineage kwargs (correlation_id / causation_id / producer /
    schema_version / aggregate_version), V12 lineage (decision_id / effect_id),
    and the §19 scope kwargs (workspace_id / location_id) are optional and
    default to the base envelope's defaults, so v1 callers keep working unchanged.
    A registered §153 adapter for (event_type, schema_version) is built when present.
    """
    cls = _resolve_class(event_type, schema_version)
    if cls is None:
        raise ValidationError(
            f"event type not registered: {event_type!r}",
            details={"event_type": event_type, "registered": sorted(EVENT_TYPES)},
        )
    return cls(
        id=envelope_id or str(uuid.uuid4()),
        type=event_type,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        location_id=location_id,
        occurred_at=occurred_at or datetime.now(UTC),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
        meta=meta or {},
        correlation_id=correlation_id,
        causation_id=causation_id,
        producer=producer,
        schema_version=schema_version,
        aggregate_version=aggregate_version,
        decision_id=UUID(str(decision_id)) if decision_id else None,
        effect_id=UUID(str(effect_id)) if effect_id else None,
    )


# ---------------------------------------------------------------------------
# Type-preserving value codec
# ---------------------------------------------------------------------------
# The envelope crosses a JSON boundary twice — the JSONB ``outbox_events``
# column and the Redis Streams field — and ``json`` cannot represent a
# ``Decimal`` / ``datetime`` / ``UUID``: it degrades each to a string, so
# ``deserialize(serialize(x)) != x``. That mattered because money is a
# ``Decimal``: ``orders/service.py`` publishes ``grand_total`` as one on
# ``order.created``, so a consumer saw ``"76.50"`` where the producer built
# ``Decimal("76.50")``.
#
# A value the JSON codec cannot carry is therefore wrapped in a self-describing
# tag ``{"__event_value__": "<type>", "value": "<text>"}``. The wire stays pure
# JSON (JSONB and Redis are happy) and the type travels WITH the value, so
# ``deserialize()`` restores it exactly. Envelope ROUTING keys in ``meta`` are
# deliberately left untagged: the SSE gateway and the relay read them as plain
# strings and they are JSON-native by construction. Rows written before this
# change hold the untagged string form and still deserialize (as strings) — the
# encoding is additive, so no migration is required.
_VALUE_TAG = "__event_value__"

_DECODERS: dict[str, Callable[[Any], Any]] = {
    "decimal": Decimal,
    "datetime": datetime.fromisoformat,
    "uuid": UUID,
}


def _encode_value(value: Any) -> Any:
    """Recursively tag values the JSON codec would otherwise stringify."""
    if isinstance(value, Decimal):
        return {_VALUE_TAG: "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {_VALUE_TAG: "datetime", "value": value.isoformat()}
    if isinstance(value, UUID):
        return {_VALUE_TAG: "uuid", "value": str(value)}
    if isinstance(value, dict):
        return {key: _encode_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_encode_value(item) for item in value]
    return value


def _decode_value(value: Any) -> Any:
    """Inverse of :func:`_encode_value` — restore tagged values to Python types."""
    if isinstance(value, dict):
        tag = value.get(_VALUE_TAG)
        decoder = _DECODERS.get(tag) if isinstance(tag, str) else None
        if decoder is not None and set(value) <= {_VALUE_TAG, "value"}:
            return decoder(value["value"])
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value


def serialize(envelope: EventEnvelope) -> dict[str, str]:
    """Map an envelope onto bus fields: ``payload`` + ``meta`` as JSON strings.

    ``meta`` carries routing (type / tenant / version / aggregate identity)
    merged over the envelope's user meta; routing keys always win. Payload and
    user-meta values are tagged by :func:`_encode_value`, so the pair is
    type-preserving (see the codec note above).

    ``mode="python"`` keeps the payload's Python types (a narrowed subclass
    dumps to a plain dict but a ``Decimal`` stays a ``Decimal``); routing keys
    come from ``mode="json"`` so they remain plain JSON scalars.
    """
    data = envelope.model_dump(mode="json")
    python_data = envelope.model_dump(mode="python")
    meta: dict[str, Any] = {
        key: _encode_value(value)
        for key, value in python_data["meta"].items()
        if key not in ROUTING_KEYS
    }
    meta.update(
        {
            "id": data["id"],
            "type": data["type"],
            "version": data["version"],
            "tenant_id": data["tenant_id"],
            "workspace_id": data["workspace_id"],
            "location_id": data["location_id"],
            "occurred_at": data["occurred_at"],
            "aggregate_type": data["aggregate_type"],
            "aggregate_id": data["aggregate_id"],
            "correlation_id": data["correlation_id"],
            "causation_id": data["causation_id"],
            "producer": data["producer"],
            "schema_version": data["schema_version"],
            "aggregate_version": data["aggregate_version"],
            "decision_id": data.get("decision_id"),
            "effect_id": data.get("effect_id"),
        }
    )
    return {
        "payload": json.dumps(_encode_value(python_data["payload"]), default=str),
        "meta": json.dumps(meta, default=str),
    }


def deserialize(fields: Mapping[str, Any]) -> EventEnvelope:
    """Rebuild an envelope from serialized fields (wire format or parsed).

    Accepts ``payload`` / ``meta`` either as JSON strings (as stored by the
    bus) or as already-parsed dicts (as yielded by RedisStreamsBus.consume).
    Tagged values (see :func:`_encode_value`) are restored to their Python
    types, so ``deserialize(serialize(x))`` is type-preserving.
    """
    payload = _decode_value(_ensure_dict(fields.get("payload", "{}")))
    meta = _decode_value(_ensure_dict(fields.get("meta", "{}")))
    event_type = meta.get("type")
    schema_version = int(meta.get("schema_version", 1))
    cls = _resolve_class(event_type, schema_version) if isinstance(event_type, str) else None
    if cls is None:
        raise ValidationError(
            f"event type not registered: {event_type!r}",
            details={"event_type": event_type, "registered": sorted(EVENT_TYPES)},
        )
    return cls(
        id=meta.get("id") or str(uuid.uuid4()),
        type=event_type,
        version=int(meta.get("version", 1)),
        tenant_id=meta["tenant_id"],
        workspace_id=meta.get("workspace_id"),
        location_id=meta.get("location_id"),
        occurred_at=datetime.fromisoformat(meta["occurred_at"]),
        aggregate_type=meta["aggregate_type"],
        aggregate_id=meta["aggregate_id"],
        correlation_id=meta.get("correlation_id"),
        causation_id=meta.get("causation_id"),
        producer=meta.get("producer", "core"),
        schema_version=schema_version,
        aggregate_version=meta.get("aggregate_version"),
        decision_id=UUID(str(meta["decision_id"])) if meta.get("decision_id") else None,
        effect_id=UUID(str(meta["effect_id"])) if meta.get("effect_id") else None,
        payload=payload,
        meta={k: v for k, v in meta.items() if k not in ROUTING_KEYS},
    )


def deserialize_event(event: Any) -> EventEnvelope:
    """Rebuild the §19 envelope a bus event carries.

    Consumers (the workers, the SSE gateway, the relay) receive an ``Event``
    whose ``payload`` / ``meta`` are already parsed; this is the read half of
    the writer's contract, so they never hand-derive envelope field names.
    """
    return deserialize(
        {
            "payload": getattr(event, "payload", None) or {},
            "meta": getattr(event, "meta", None) or {},
        }
    )


def _ensure_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str | bytes | bytearray):
        value = json.loads(value)
    return dict(value or {})
