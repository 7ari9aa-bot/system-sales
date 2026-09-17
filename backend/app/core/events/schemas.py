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
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.errors import ValidationError

EVENT_TYPES: dict[str, type[EventEnvelope]] = {}

# Meta keys that carry envelope routing rather than user-supplied metadata.
ROUTING_KEYS: frozenset[str] = frozenset(
    {"id", "type", "version", "tenant_id", "occurred_at", "aggregate_type", "aggregate_id"}
)


def register_event(name: str) -> Callable[[type[EventEnvelope]], type[EventEnvelope]]:
    """Register an envelope class under an event type name (e.g. "order.created").

    Re-registering the same class under the same name is a no-op; a different
    class for a taken name is a programming error and raises ValueError.
    """

    def decorator(cls: type[EventEnvelope]) -> type[EventEnvelope]:
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
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


def build_envelope(
    event_type: str,
    *,
    tenant_id: UUID | str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    payload: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    envelope_id: str | None = None,
) -> EventEnvelope:
    """Build a registered envelope; unknown event types are rejected."""
    cls = EVENT_TYPES.get(event_type)
    if cls is None:
        raise ValidationError(
            f"event type not registered: {event_type!r}",
            details={"event_type": event_type, "registered": sorted(EVENT_TYPES)},
        )
    return cls(
        id=envelope_id or str(uuid.uuid4()),
        type=event_type,
        tenant_id=tenant_id,
        occurred_at=occurred_at or datetime.now(UTC),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
        meta=meta or {},
    )


def serialize(envelope: EventEnvelope) -> dict[str, str]:
    """Map an envelope onto bus fields: ``payload`` + ``meta`` as JSON strings.

    ``meta`` carries routing (type / tenant / version / aggregate identity)
    merged over the envelope's user meta; routing keys always win.
    """
    data = envelope.model_dump(mode="json")
    meta: dict[str, Any] = {k: v for k, v in data["meta"].items() if k not in ROUTING_KEYS}
    meta.update(
        {
            "id": data["id"],
            "type": data["type"],
            "version": data["version"],
            "tenant_id": data["tenant_id"],
            "occurred_at": data["occurred_at"],
            "aggregate_type": data["aggregate_type"],
            "aggregate_id": data["aggregate_id"],
        }
    )
    return {
        "payload": json.dumps(data["payload"], default=str),
        "meta": json.dumps(meta, default=str),
    }


def deserialize(fields: Mapping[str, Any]) -> EventEnvelope:
    """Rebuild an envelope from serialized fields (wire format or parsed).

    Accepts ``payload`` / ``meta`` either as JSON strings (as stored by the
    bus) or as already-parsed dicts (as yielded by RedisStreamsBus.consume).
    """
    payload = _ensure_dict(fields.get("payload", "{}"))
    meta = _ensure_dict(fields.get("meta", "{}"))
    event_type = meta.get("type")
    cls = EVENT_TYPES.get(event_type) if isinstance(event_type, str) else None
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
        occurred_at=datetime.fromisoformat(meta["occurred_at"]),
        aggregate_type=meta["aggregate_type"],
        aggregate_id=meta["aggregate_id"],
        payload=payload,
        meta={k: v for k, v in meta.items() if k not in ROUTING_KEYS},
    )


def _ensure_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str | bytes | bytearray):
        value = json.loads(value)
    return dict(value or {})
