"""Worker log correlation (O10: "worker logs lack correlation ids").

The API path already had lineage. ``app.main._RequestIDMiddleware`` publishes
``request_id_contextvar`` and ``correlation_id_contextvar``, the v2 error
envelope reads the former, and ``add_outbox_event`` stamps it onto every event
so a domain event traces back to the request that caused it.

A worker consumes Redis Streams OUTSIDE any HTTP request, so it had no id at
all. ``StreamWorker._run_with_lineage`` already set ``correlation_id_contextvar``
— for the AUDIT writer, which reads it to stamp ``audit_logs.correlation_id`` —
but no log line ever rendered it: the worker modules use plain stdlib
``logging`` and ``logging.basicConfig(format=...)`` names no such field. So the
lineage existed in a contextvar nothing printed.

This module closes that with three pieces:

1. :func:`correlation_id_for_event` — the id ONE message is known by. The
   envelope's own ``correlation_id`` when it has one (that is the request id
   that caused it), else a stable per-MESSAGE fallback: the outbox row id, then
   the envelope id. Never ``entry_id`` and never a fresh uuid, because both
   change between deliveries and would defeat the whole point — a retried or
   reclaimed message must land under the SAME id.
2. :func:`bind_message` / :func:`bind_pool` — the scope a log line is emitted
   under. ``run()`` binds the pool so no worker line is ever un-attributed;
   ``_process`` overrides that with the message for the duration of one event,
   including the runtime's own failure / retry / dead-letter lines.
3. :func:`install_log_correlation` — a log record factory that stamps
   ``record.correlation_id`` on EVERY record this process creates, so the field
   is available to the worker's format string (`app.workers.run.WORKER_LOG_FORMAT`)
   without threading a logger adapter through ~50 call sites.

Imported for its install side effect by ``app.workers.base``, which every pool
subclasses, so a worker process cannot start without it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.core.errors import ValidationError
from app.core.events.schemas import deserialize_event

#: The attribute the worker log format renders. Keep in sync with
#: ``app.workers.run.WORKER_LOG_FORMAT`` — ``tests/test_worker_correlation_logging.py``
#: pins that the shipped format actually names this field.
CORRELATION_ATTR = "correlation_id"

#: What a line outside any message scope reports. A worker pool's own lifecycle
#: lines (``worker.started``, ``worker.stream_timeout``) belong to the pool, not
#: to a message, and an empty value would read like a bug rather than a scope.
NO_SCOPE = "-"

_log_correlation: ContextVar[str] = ContextVar(
    "worker_log_correlation", default=NO_SCOPE
)

_factory_installed = False
_previous_factory: Callable[..., logging.LogRecord] | None = None


def current_correlation_id() -> str:
    """The correlation id lines logged RIGHT NOW belong to."""
    return _log_correlation.get()


def correlation_id_for_event(event: Any) -> str:
    """The one id under which THIS message is logged, on every attempt.

    Resolution order, and why:

    * ``envelope.correlation_id`` — the request that caused the event. The
      retry path re-stages the row with it (``_republish_after`` passes it to
      ``add_outbox_event`` explicitly), so a retry keeps it by construction.
    * ``meta["outbox_id"]`` — the consumer-inbox dedupe key, which the retry
      path copies from the original row ON PURPOSE ("a retry must dedupe
      against the attempt it is retrying"). Reusing it means the log id and the
      dedupe id agree, and both survive the staging round trip.
    * ``meta["id"]`` / ``event.id`` — the envelope id, which ``serialize`` puts
      back on the wire, so a reclaim re-reads the same value.
    * ``NO_SCOPE`` — nothing stable at all; still never a fresh uuid.
    """
    try:
        correlation_id = deserialize_event(event).correlation_id
    except (ValidationError, KeyError, TypeError, ValueError):
        correlation_id = None
    if correlation_id:
        return str(correlation_id)

    meta = getattr(event, "meta", None) or {}
    for key in ("outbox_id", "id"):
        value = meta.get(key)
        if value:
            return str(value)
    event_id = getattr(event, "id", None)
    if event_id:
        return str(event_id)
    return NO_SCOPE


@contextmanager
def bind_message(event: Any) -> Iterator[str]:
    """Log everything inside under ``event``'s correlation id."""
    correlation_id = correlation_id_for_event(event)
    token = _log_correlation.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _log_correlation.reset(token)


@contextmanager
def bind_pool(stream: str) -> Iterator[str]:
    """The pool-level scope: lines that belong to no single message."""
    correlation_id = f"pool:{stream}" if stream else NO_SCOPE
    token = _log_correlation.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _log_correlation.reset(token)


def _stamping_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _previous_factory(*args, **kwargs)  # type: ignore[misc]
    # setdefault, not assignment: a caller that already named a correlation
    # explicitly (``logger.info(..., correlation_id=x)``) wins.
    if not hasattr(record, CORRELATION_ATTR):
        setattr(record, CORRELATION_ATTR, current_correlation_id())
    return record


def install_log_correlation() -> None:
    """Stamp ``correlation_id`` onto every record this process creates.

    Idempotent, and chains rather than replaces any factory already installed,
    so it composes with ``logging.config`` and with test harnesses.
    """
    global _factory_installed, _previous_factory
    if _factory_installed:
        return
    _previous_factory = logging.getLogRecordFactory()
    logging.setLogRecordFactory(_stamping_factory)
    _factory_installed = True


__all__ = [
    "CORRELATION_ATTR",
    "NO_SCOPE",
    "bind_message",
    "bind_pool",
    "correlation_id_for_event",
    "current_correlation_id",
    "install_log_correlation",
]
