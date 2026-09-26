"""The connection-pool invariant, pinned so it cannot be broken silently.

GAP_REGISTER's measured arithmetic: the worker process holds TWO connections
per in-flight event — the §127/ADR-058 claim transaction stays open across the
whole effect, and every handler opens its own session beside it. With one
relay + every pool in `POOLS` running in one process on one engine, the pool
must satisfy::

    pool_size + max_overflow  >=  2 * (len(POOLS) + 1) + headroom

or the next added pool, nested handler session, or concurrency bump converts
into 30-second pool `TimeoutError`s that look nothing like a database problem
(the engine used SQLAlchemy's silent defaults — 15 connections — and fit by
ONE unit until this file existed).

DB-free: this reads the declared pools and the settings, not a connection.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.workers.run import POOLS

#: Capacity the orchestrating process itself needs beyond the pools' claims —
#: the relay's per-row sessions and one retry-staging session (workers/base.py
#: `_republish_after`) open beside the claims.
RELAY = 1
HEADROOM = 4


def test_the_pool_covers_two_connections_per_in_flight_event() -> None:
    settings = get_settings()
    required = 2 * (len(POOLS) + RELAY) + HEADROOM
    available = settings.db_pool_size + settings.db_max_overflow

    assert available >= required, (
        f"db_pool_size({settings.db_pool_size}) + db_max_overflow("
        f"{settings.db_max_overflow}) = {available}, but {len(POOLS)} pools "
        f"+ {RELAY} relay hold two connections per in-flight event, so "
        f"{required} is the floor (+{HEADROOM} headroom). Raise the pool or "
        f"cut concurrency — a pool that does not fit times out as a 30 s "
        f"TimeoutError, not a database error."
    )


def test_the_pool_is_declared_not_defaulted() -> None:
    """SQLAlchemy's defaults (5 + 10) are exactly what this file exists to end."""
    settings = get_settings()
    declared = (settings.db_pool_size, settings.db_max_overflow)
    assert declared != (5, 10), (
        "the engine fell back to SQLAlchemy's silent defaults — the GAP_REGISTER "
        "capacity incident is the reason these are explicit"
    )
