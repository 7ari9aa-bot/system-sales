"""P-02's backoff parameters must arrive at Postgres as doubles, not as integers.

`_MARK_FAILED_SQL` computes the next-try schedule from two bind parameters whose
values come out of settings and constants:

    outbox_failed_requeue_seconds: float = 300.0      (app/core/config.py)
    OUTBOX_BACKOFF_CEILING_SECONDS = 3600.0           (app/core/events/outbox.py)

Both are floats, and they belong in floats: a fractional cool-down is a valid
operator setting, and `power(2, …)` already makes the product a double. The
hazard is Postgres parameter type inference. `GREATEST(:base, 0)` has one
known-type input — the integer literal — and GREATEST resolves to the type of
its non-unknown arguments, so the server tells the driver `int4` for `:base`.
asyncpg then hands it 300.0 and refuses it
(`invalid input for query argument $1: 300.0 (expected int, got float)`) —
which means the relay's failure path raises on the way to marking a row failed,
turning "the bus is down" into "the relay is broken". Every parse of this
statement by a client-side parser passes; only the server's type resolution
knows.

So each of the two parameters is wrapped in an explicit
`CAST(… AS double precision)`. The other half of this file guards how that gets
written: SQLAlchemy's `text()` tokenizer does NOT treat `:base::double` as a
cast of `:base` — it reads the parameter as `bas` and leaves `e::double` behind,
so the shorter Postgres spelling silently renames the bind and the drain dies
with a missing-parameter error instead. `CAST(:base AS double precision)` is the
only form that types the parameter and keeps its name.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.core.config import Settings
from app.core.events.outbox import (
    _MARK_FAILED_SQL,
    OUTBOX_BACKOFF_CEILING_SECONDS,
)

_MARK = str(_MARK_FAILED_SQL)


def _bound_params(sql: str) -> set[str]:
    """The names SQLAlchemy will actually send, from its own tokenizer."""
    return set(sa.text(sql)._bindparams)


def test_the_backoff_inputs_are_floats_not_ints() -> None:
    """The premise of the whole file. If either becomes an int, this test's
    other half is moot and says so here rather than in a relay traceback."""
    assert isinstance(Settings.model_fields["outbox_failed_requeue_seconds"].default, float)
    assert isinstance(OUTBOX_BACKOFF_CEILING_SECONDS, float)


def test_the_drain_sends_both_backoff_parameters_it_declares() -> None:
    """A typo in either direction — the SQL renames a bind, or the drain stops
    sending one — is a runtime error in the relay's exception handler. This is
    the cheap check that the two agree, by name, on the real statement."""
    declared = _bound_params(_MARK)
    drain_body = _drain_source()

    for name in declared:
        assert f'"{name}"' in drain_body, (
            f"`_MARK_FAILED_SQL` binds `{name}` but the drain never passes it"
        )
    for name in ("backoff_base_seconds", "backoff_max_seconds"):
        assert name in drain_body, f"the drain stopped passing `{name}`"
        assert name in declared, f"the drain passes `{name}` but the SQL no longer asks for it"


def test_every_backoff_parameter_is_cast_to_a_type_that_holds_a_float() -> None:
    """`GREATEST(:param, 0)` lands on int4 without an explicit double cast."""
    for name in ("backoff_base_seconds", "backoff_max_seconds"):
        assert f"CAST(:{name} AS double precision)" in _MARK, (
            f"`{name}` is sent untyped: Postgres resolves it from its integer "
            f"siblings in GREATEST/LEAST, the driver is told int4, and the float "
            f"the setting holds is rejected. Spell it "
            f"`CAST(:{name} AS double precision)`."
        )


def test_the_cast_spelling_keeps_the_parameter_names() -> None:
    """Guards the replacement itself: `::` is a valid Postgres cast and an
    invalid SQLAlchemy bind name, so this is the difference between a typed
    parameter and a statement the drain cannot fill."""
    colon_form = "SELECT GREATEST(:backoff_base_seconds::double precision, 0)"

    assert "backoff_base_seconds" not in _bound_params(colon_form), (
        "SQLAlchemy stopped mangling `:name::type`; the CAST-free spelling would "
        "now be safe and this guard should be re-read, not deleted"
    )
    assert "backoff_base_seconds" in _bound_params(_MARK)


def _drain_source() -> str:
    import inspect

    from app.core.events.outbox import OutboxRelay

    return inspect.getsource(OutboxRelay._drain_once)
