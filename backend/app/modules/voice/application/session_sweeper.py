"""The sweeper: the only thing that ends a session nobody is holding any more.

A voice session's ending is written by the socket that carried the call. Every
other way a call stops — the worker is replaced mid-call, a laptop sleeps, the
tab is closed before the provider ever connected, the process is killed — skips
that ``finally`` and leaves a row saying ``CONFIGURING`` or ``ACTIVE`` forever.
Measured on the owner's live database before this file existed: 30 voice
sessions, every one of them ``CONFIGURING``, none ever ended.

Two questions decide what a stale row has earned, and they are answered by
``ending_for`` as a pure function so the rules can be read without a database:

* **Did it expire?** ``capability.expires_at`` is minted with the session (one
  hour today). A call past its own lifetime is over whatever the row says.
* **Did it go silent?** There is no heartbeat, so the only evidence a call is
  still alive is that something touched the row — a state move, a completed
  turn. Silence is a PROXY, and it is worth being exact about what it gets
  wrong: a call where the person is thinking, or where every turn fails to
  complete, touches nothing and looks as dead as a closed tab. What saves it is
  the budget, not the signal. A call that has not finished CONFIGURING in
  ``DEFAULT_CONFIGURING_GRACE`` never reached the provider, while an ``ACTIVE``
  call is only presumed dead after the much more generous
  ``DEFAULT_STALE_AFTER`` — far longer than any turn this runtime can take, so a
  working call is only ever swept while genuinely idle for half an hour. Both are
  deliberately forgiving: ending a real call is worse than ending a dead row late.

  The budgets are settings (``VOICE_SWEEP_STALE_AFTER_MINUTES`` /
  ``VOICE_SWEEP_CONFIGURING_GRACE_MINUTES``), because the right silence budget is
  a property of how a shop uses the phone line, not of this code. A heartbeat
  written by the media pump is the real fix; until it exists, this is the
  stopgap, and ``tests/voice/test_voice_session_sweeper.py`` pins both sides of
  the trade-off: a long call that keeps completing turns is never swept, and a
  long silence is swept at the threshold and not a minute sooner.

The ending itself is not invented here. A ``CONFIGURING`` session never named a
provider, and the state machine has no edge from ``CONFIGURING`` to ``CLOSING``,
so it can only FAIL — which is what ``fail`` writes. An expired ``ACTIVE``
session is a call that ran its course, so it closes; an ``ACTIVE`` session that
went silent lost its media path and fails with ``connection_lost``.

Two rules are structural, not stylistic:

* every write goes through ``VoiceSessionManager``, the same service the socket
  uses, so the sweeper cannot make a move the state machine refuses;
* this module only ``flush()``es. The caller owns the transaction and commits —
  ``app.workers.voice_session_sweeper`` does that once per tenant, with
  ``bind_tenant``, because ``voice_sessions`` is FORCE RLS.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import or_, select

from app.core.errors import ConflictError, NotFoundError
from app.modules.voice.application.session_manager import VoiceSessionManager
from app.modules.voice.domain.models import VoiceSessionRow
from app.modules.voice.domain.states import IllegalTransition, VoiceSessionState
from app.modules.voice.infrastructure.sql_store import SqlSessionStore

logger = logging.getLogger(__name__)

#: How long an ``ACTIVE`` call may go untouched before it is treated as gone. A
#: call that has not moved state and completed no turn for this long is not a
#: conversation anybody is having; without a heartbeat it is the only evidence.
DEFAULT_STALE_AFTER = dt.timedelta(minutes=30)

#: How long a session may sit in ``CONFIGURING`` before it is treated as a start
#: that never reached the provider. Short, because nothing is being said yet: the
#: only work a real start does here is minting a capability and opening a socket.
DEFAULT_CONFIGURING_GRACE = dt.timedelta(minutes=5)

#: A tenant's sweep is bounded so one shop with a pathological table cannot hold
#: the transaction open for every other shop. The next run picks up the rest.
DEFAULT_LIMIT = 200

#: The states this sweep owns. Every other state either is terminal already or
#: belongs to a live handoff that a person is holding.
SWEPT_STATES: tuple[VoiceSessionState, ...] = (
    VoiceSessionState.CONFIGURING,
    VoiceSessionState.ACTIVE,
)

#: Why a row was ended, in the vocabulary the row keeps in ``close_reason``.
EXPIRED = "expired"
EXPIRED_BEFORE_CONNECT = "expired_before_connect"
CONNECTION_LOST = "connection_lost"
CONNECT_TIMEOUT = "connect_timeout"

Action = Literal["close", "fail"]


@dataclass(frozen=True, slots=True)
class Ending:
    """What a stale session has earned: which move, and the reason written with it."""

    action: Action
    reason: str


@dataclass(frozen=True, slots=True)
class SweepOutcome:
    """What one tenant's sweep did. Plain data, so it outlives the transaction."""

    scanned: int = 0
    closed: int = 0
    failed: int = 0

    @property
    def ended(self) -> int:
        return self.closed + self.failed

    def as_dict(self) -> dict[str, int]:
        return {"scanned": self.scanned, "closed": self.closed, "failed": self.failed}


def _utc(value: dt.datetime | None) -> dt.datetime | None:
    """Read a timestamp as UTC. A naive one came from a test or a driver, not from Postgres."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def ending_for(
    state: VoiceSessionState | str,
    *,
    expires_at: dt.datetime | None,
    updated_at: dt.datetime | None,
    now: dt.datetime,
    stale_after: dt.timedelta = DEFAULT_STALE_AFTER,
    configuring_grace: dt.timedelta = DEFAULT_CONFIGURING_GRACE,
) -> Ending | None:
    """The ending this row has earned, or ``None`` when the call may still be real.

    Expiry wins over silence: an expired call is over on its own terms, and the
    reason should say so rather than blaming the network. A state this sweep does
    not own — a terminal one, or a handoff a person is holding — has earned
    nothing and is left exactly as it is.
    """
    current = VoiceSessionState(state)
    if current not in SWEPT_STATES:
        return None

    expires = _utc(expires_at)
    touched = _utc(updated_at)
    expired = expires is not None and expires <= now

    if current is VoiceSessionState.CONFIGURING:
        # CONFIGURING has no edge to CLOSING: a call that never named a provider
        # can only be recorded as failed, with a reason that says which half of
        # the start it died in. A row with no updated_at at all has never been
        # touched by anything this code can see; treat it as silent rather than
        # immortal.
        if expired:
            return Ending("fail", EXPIRED_BEFORE_CONNECT)
        if touched is None or touched <= now - configuring_grace:
            return Ending("fail", CONNECT_TIMEOUT)
        return None

    if expired:
        return Ending("close", EXPIRED)
    if touched is None or touched <= now - stale_after:
        return Ending("fail", CONNECTION_LOST)
    return None


def _manager(session: Any) -> VoiceSessionManager:
    """The service that owns the row, built on this sweep's transaction.

    Behind a function so a test can drive the sweep without a database, the same
    shape ``assistant_turn`` uses for the same reason.
    """
    return VoiceSessionManager(SqlSessionStore(session))


async def sweep_tenant_sessions(
    session: Any,
    tenant_id: uuid.UUID,
    *,
    now: dt.datetime | None = None,
    stale_after: dt.timedelta = DEFAULT_STALE_AFTER,
    configuring_grace: dt.timedelta = DEFAULT_CONFIGURING_GRACE,
    limit: int = DEFAULT_LIMIT,
) -> SweepOutcome:
    """End this tenant's abandoned sessions. FLUSH ONLY — the caller commits.

    The select takes ``FOR UPDATE SKIP LOCKED`` so a sweep running on two
    replicas cannot both end the same row, and so a row a live turn is writing
    is skipped rather than raced. Its filter is deliberately LOOSE — anything
    expired or quiet for the shortest grace — because ``ending_for`` is the one
    place that decides; ordering by ``updated_at`` puts the genuinely stale rows
    first, so a bounded window cannot be filled by rows that turn out to be fine.

    A session somebody else ended between the select and the write is not an
    error: the ending already happened, which is all this sweep wanted. Any other
    failure is logged against that one session and the sweep continues — one bad
    row must never leave the rest of a shop's sessions stuck.
    """
    moment = now or dt.datetime.now(dt.UTC)
    quietest = min(stale_after, configuring_grace)

    rows = (
        (
            await session.execute(
                select(VoiceSessionRow)
                .where(
                    VoiceSessionRow.tenant_id == tenant_id,
                    VoiceSessionRow.state.in_([state.value for state in SWEPT_STATES]),
                    or_(
                        VoiceSessionRow.expires_at <= moment,
                        VoiceSessionRow.updated_at <= moment - quietest,
                        # A row nothing has ever stamped has no evidence of life at all, and
                        # ``ending_for`` calls that silent. Leaving it out of the SELECT while the
                        # decision calls it stale is how a row stays CONFIGURING forever: the one
                        # row the sweep exists for is the one row it never looked at.
                        VoiceSessionRow.updated_at.is_(None),
                    ),
                )
                # NULLs first: with the default (NULLs last) a window full of live calls could
                # fill the bounded limit and never reach the untouched rows behind them.
                .order_by(VoiceSessionRow.updated_at.asc().nullsfirst())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )

    manager = _manager(session)
    closed = 0
    failed = 0
    for row in rows:
        # Copy what the decision needs into plain values BEFORE any write. Reading
        # an ORM attribute after a flush is the MissingGreenlet trap this repo has
        # a guard test for, and a sweep is exactly the loop that would hit it.
        session_id = row.id
        try:
            ending = ending_for(
                row.state,
                expires_at=row.expires_at,
                updated_at=row.updated_at,
                now=moment,
                stale_after=stale_after,
                configuring_grace=configuring_grace,
            )
            if ending is None:
                continue
            if ending.action == "close":
                await manager.close(session_id, reason=ending.reason, tenant_id=tenant_id)
                closed += 1
            else:
                await manager.fail(session_id, reason=ending.reason)
                failed += 1
        except (ConflictError, IllegalTransition, NotFoundError):
            # Another writer got there first (a socket that finally ran its own
            # finally, another replica's sweep). The row is ended either way.
            logger.info("voice.session_sweep_already_ended session=%s", session_id)
        except Exception:  # noqa: BLE001 - one bad session must never stop the sweep
            logger.exception("voice.session_sweep_row_failed session=%s", session_id)

    outcome = SweepOutcome(scanned=len(rows), closed=closed, failed=failed)
    if outcome.ended:
        logger.info(
            "voice.session_sweep tenant=%s scanned=%d closed=%d failed=%d",
            tenant_id,
            outcome.scanned,
            outcome.closed,
            outcome.failed,
        )
    return outcome
