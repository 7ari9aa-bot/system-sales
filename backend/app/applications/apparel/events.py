"""The events FIHRIST Apparel publishes.

The platform owns the envelope: id, type, schema version, tenant, workspace,
aggregate, occurred at, correlation, payload (industry-applications §17). What
the platform must not own is the list of sector events, so this module turns the
manifest's event names into wire names and registers them at startup. Adding a
shirt event is then a change in the apparel package, not in the platform.

Wire names are ``apparel.<module>.<event_in_snake_case>``, so a consumer can
route on the prefix without a table of every application.
"""

from __future__ import annotations

import re

from app.applications.apparel.manifest import MODULES
from app.core.events.schemas import EVENT_TYPES, EventEnvelope, register_event

PREFIX = "apparel."


def _snake(name: str) -> str:
    """``ProductCreated`` -> ``product_created``."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def wire_name(module: str, event: str) -> str:
    return f"{PREFIX}{module}.{_snake(event)}"


def event_names() -> tuple[str, ...]:
    """Every wire name this release publishes, in manifest order."""
    return tuple(wire_name(module.key, event) for module in MODULES for event in module.events)


def register() -> tuple[str, ...]:
    """Register every apparel event type. Idempotent: startup may run twice."""
    names = event_names()
    for name in names:
        register_event(name)(EventEnvelope)
    return names


def is_registered(name: str) -> bool:
    return name in EVENT_TYPES


__all__ = ["PREFIX", "event_names", "is_registered", "register", "wire_name"]
