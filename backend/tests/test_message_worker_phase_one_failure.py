"""A message that dies BEFORE the provider call must still ring the owner's bell (M10).

Phase 3 of `_deliver` notified a failed SEND. A `PermanentError` raised in phase 1 (a reaction
without its target, an uploaded file the bucket will not read, a channel with no adapter) marked the
message failed and dead-lettered the event, and nobody was told: the customer's question went
unanswered while the merchant believed the bot was working.

DB-free on purpose: these drive `_deliver` with a fake session, so the wiring (the bell rings after
the commit, before the dead-letter, with the right ids) is checked without Postgres. The row the
bell writes is covered by test_outbound_delivery_notification.py.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.workers import message_worker as mw
from app.workers.base import PermanentError
from app.workers.message_worker import MessageWorker


class _FakeSession:
    def __init__(self, log: list[str]):
        self._log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        log = self._log

        class _Tx:
            async def __aenter__(self_inner):
                log.append("begin")
                return self_inner

            async def __aexit__(self_inner, *exc):
                log.append("commit" if exc[0] is None else "rollback")
                return False

        return _Tx()

    async def flush(self):
        self._log.append("flush")


@pytest.fixture
def wired(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(mw, "SessionLocal", lambda: _FakeSession(log))

    async def _bind(_session, _tenant):
        log.append("bind")

    async def _allow(*_a, **_k):
        return None

    monkeypatch.setattr(mw, "bind_tenant", _bind)
    monkeypatch.setattr(mw, "defer_unless_tenant_allows", _allow)
    return log


def _envelope(tenant_id, message_id):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, payload={"message_id": str(message_id)}
    )


async def test_a_phase_one_permanent_error_rings_the_bell_after_the_commit(wired, monkeypatch):
    tenant_id, message_id = uuid.uuid4(), uuid.uuid4()
    worker = MessageWorker(bus=MagicMock())

    async def _boom(*_a, **_k):
        raise PermanentError("uploaded file could not be read")

    async def _bell(tenant, message, reason):
        wired.append(f"bell:{tenant}:{message}:{reason}")

    monkeypatch.setattr(worker, "_deliver_one", _boom)
    monkeypatch.setattr(worker, "_notify_phase_one_failure", _bell)

    with pytest.raises(PermanentError, match="could not be read"):
        await worker._deliver(_envelope(tenant_id, message_id))

    assert f"bell:{tenant_id}:{message_id}:uploaded file could not be read" in wired
    # The failed status is committed BEFORE the bell, so it never names a rolled-back row.
    assert wired.index("commit") < next(i for i, e in enumerate(wired) if e.startswith("bell:"))


async def test_a_successful_phase_one_rings_nothing(wired, monkeypatch):
    worker = MessageWorker(bus=MagicMock())
    rang = []

    async def _no_plan(*_a, **_k):
        return None

    async def _bell(*a, **k):
        rang.append(a)

    monkeypatch.setattr(worker, "_deliver_one", _no_plan)
    monkeypatch.setattr(worker, "_notify_phase_one_failure", _bell)

    await worker._deliver(_envelope(uuid.uuid4(), uuid.uuid4()))

    assert rang == []


async def test_a_bell_that_cannot_be_written_never_replaces_the_real_error(monkeypatch):
    """Best-effort by contract: the failure is already committed."""
    worker = MessageWorker(bus=MagicMock())

    class _ExplodingSession:
        async def __aenter__(self):
            raise ConnectionError("db went away")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mw, "SessionLocal", lambda: _ExplodingSession())

    await worker._notify_phase_one_failure(uuid.uuid4(), uuid.uuid4(), "reason")  # must not raise
