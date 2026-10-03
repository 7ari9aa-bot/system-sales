"""Graceful worker shutdown tests (audit P1/R3) — drain, crash, redis close.

The platform sends SIGTERM on every deploy and scale-down. The run loop must
stop the cooperative worker loops (their own _running flags), give in-flight
events the grace window, propagate a crashed pool's exception (crash-only
supervision), and close redis exactly once.
"""

from __future__ import annotations

import asyncio

import pytest

from app.workers import run as worker_run


class _FakeBus:
    pass


class _FakeWorker:
    """StreamWorker-shaped: run() loops until stop(), then exits cleanly."""

    instances: list = []

    def __init__(self, bus):
        self.stopped = False
        self.ran = False
        _FakeWorker.instances.append(self)

    def stop(self):
        self.stopped = True

    async def run(self):
        self.ran = True
        while not self.stopped:
            await asyncio.sleep(0.01)


class _CrashingWorker(_FakeWorker):
    async def run(self):
        self.ran = True
        raise RuntimeError("pool crashed")


async def _patch_world(monkeypatch, monkey_close=True):
    _FakeWorker.instances = []
    monkeypatch.setattr(worker_run, "get_redis", lambda: object())
    monkeypatch.setattr(worker_run, "RedisStreamsBus", lambda redis: _FakeBus())
    monkeypatch.setattr(worker_run, "POOLS", {"fake": _FakeWorker})
    if monkey_close:
        closed = {"count": 0}

        async def fake_close():
            closed["count"] += 1

        monkeypatch.setattr(worker_run, "close_redis", fake_close)
        return closed


async def test_stop_event_drains_workers_and_closes_redis(monkeypatch):
    closed = await _patch_world(monkeypatch)
    stop = asyncio.Event()
    task = asyncio.create_task(worker_run.main(["fake"], stop=stop))
    await asyncio.sleep(0.05)  # let the worker loop start
    assert _FakeWorker.instances[0].ran
    stop.set()
    # The drain grace is 15s — the wait must exceed it.
    await asyncio.wait_for(task, timeout=20)
    assert _FakeWorker.instances[0].stopped
    assert closed["count"] == 1


async def test_crashed_pool_exception_propagates_and_closes_redis(monkeypatch):
    closed = await _patch_world(monkeypatch)
    monkeypatch.setattr(worker_run, "POOLS", {"crash": _CrashingWorker})
    with pytest.raises(RuntimeError, match="pool crashed"):
        await worker_run.main(["crash"])
    assert closed["count"] == 1


async def test_install_signal_handlers_survives_windows(monkeypatch):
    """Windows dev loops raise NotImplementedError — the install must not."""
    monkeypatch.setattr(
        asyncio, "get_running_loop", lambda: _NoSignalLoop()
    )
    stop = asyncio.Event()
    worker_run.install_signal_handlers(stop)  # must not raise
    assert not stop.is_set()


class _NoSignalLoop:
    """asyncio loop stand-in whose add_signal_handler always refuses."""

    def add_signal_handler(self, sig, callback):
        raise NotImplementedError


async def test_unknown_pool_still_fails_loudly(monkeypatch):
    await _patch_world(monkeypatch)
    with pytest.raises(SystemExit, match="unknown pool"):
        await worker_run.main(["nonexistent"])
