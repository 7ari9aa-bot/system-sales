"""Route a published event to the application that owns it.

The platform carries the envelope and the transport, and knows nothing about
what a sector does with an event (industry-applications §17). So it must not
hold a table of application names either: an event's wire name already starts
with its application's key (``apparel.orders.sale_completed``), and that prefix
is the whole routing rule.

A consumer registers against an exact wire name. Dispatch refuses anything it
cannot attribute, so an event from an application this deployment does not run
fails loudly at the edge instead of being silently dropped.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.events.schemas import EVENT_TYPES

Handler = Callable[[dict], Awaitable[None]]


class UnknownApplicationEvent(LookupError):
    """The event name is not registered by any application in this release."""


class NoConsumer(RuntimeError):
    """The event is real, but nothing in this deployment consumes it."""


@dataclass(frozen=True)
class Route:
    application: str
    module: str
    event: str


def application_of(event_name: str) -> str:
    """``apparel.orders.sale_completed`` -> ``apparel``."""
    head, _, rest = event_name.partition(".")
    if not head or not rest:
        raise UnknownApplicationEvent(f"{event_name!r} is not an application event name")
    return head


def parse(event_name: str) -> Route:
    """Split a wire name into its parts, refusing anything malformed."""
    application = application_of(event_name)
    module, _, event = event_name[len(application) + 1 :].partition(".")
    if not module or not event:
        raise UnknownApplicationEvent(f"{event_name!r} names no module.event")
    return Route(application=application, module=module, event=event)


_CONSUMERS: dict[str, list[Handler]] = {}


def consumes(event_name: str) -> Callable[[Handler], Handler]:
    """Register a handler for one wire name. Two handlers may share an event."""

    def register(handler: Handler) -> Handler:
        _CONSUMERS.setdefault(event_name, []).append(handler)
        return handler

    return register


def consumers_for(event_name: str) -> tuple[Handler, ...]:
    return tuple(_CONSUMERS.get(event_name, ()))


def registered_events() -> tuple[str, ...]:
    return tuple(sorted(_CONSUMERS))


async def dispatch(event_name: str, payload: dict) -> int:
    """Hand one event to every consumer of it. Returns how many ran.

    Raises instead of guessing: an unregistered type means the envelope came
    from a release this deployment does not know, and an event with no consumer
    means the application published something nobody handles — both are wiring
    faults that a silent drop would hide until the shop noticed.
    """
    parse(event_name)
    if event_name not in EVENT_TYPES:
        raise UnknownApplicationEvent(event_name)
    handlers = consumers_for(event_name)
    if not handlers:
        raise NoConsumer(event_name)
    for handler in handlers:
        await handler(payload)
    return len(handlers)


__all__ = [
    "Handler",
    "NoConsumer",
    "Route",
    "UnknownApplicationEvent",
    "application_of",
    "consumers_for",
    "consumes",
    "dispatch",
    "parse",
    "registered_events",
]
