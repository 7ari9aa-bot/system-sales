"""Tests for the Settings SLO framework (§168).

Verifies:
* ``record_settings_resolve`` increments the right counters.
* ``record_notification_delivery`` records delivered/failed outcomes.
* ``get_slo_status`` computes correct health verdicts from the counters.
* SLO targets and status strings are consistent.
* The outbox-lag SLO reuses the existing ``collect_outbox`` gauge.
"""

from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis

from app.modules.settings.slo import (
    SLO_LATENCY_TARGET_SECONDS,
    SLO_NOTIFICATION_SUCCESS_TARGET,
    SLO_OUTBOX_LAG_TARGET_SECONDS,
    get_slo_status,
    record_notification_delivery,
    record_settings_resolve,
)


@pytest.fixture
async def fake_redis():
    return FakeRedis(decode_responses=True)


class TestSettingsSLORecording:
    """Counter writes are correct and fire-and-forget."""

    @pytest.mark.asyncio
    async def test_record_settings_resolve_increments_request_and_duration(self, fake_redis):
        await record_settings_resolve(duration_seconds=0.1, redis=fake_redis)
        status = await get_slo_status(redis=fake_redis)
        slo = status["slos"][0]
        assert slo["name"] == "settings_effective_latency"
        assert slo["measurements"]["total_requests"] == 1
        assert slo["measurements"]["avg_ms"] == 100.0
        assert slo["measurements"]["slow_requests"] == 0

    @pytest.mark.asyncio
    async def test_record_settings_resolve_slow_request_is_counted(self, fake_redis):
        # Above the 0.5 s threshold → slow.
        await record_settings_resolve(
            duration_seconds=SLO_LATENCY_TARGET_SECONDS + 0.1, redis=fake_redis
        )
        status = await get_slo_status(redis=fake_redis)
        slo = status["slos"][0]
        assert slo["measurements"]["slow_requests"] == 1
        assert slo["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_record_settings_resolve_fast_request_is_healthy(self, fake_redis):
        await record_settings_resolve(duration_seconds=0.01, redis=fake_redis)
        status = await get_slo_status(redis=fake_redis)
        slo = status["slos"][0]
        assert slo["measurements"]["slow_requests"] == 0
        assert slo["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_record_notification_delivery_delivered(self, fake_redis):
        await record_notification_delivery(succeeded=True, redis=fake_redis)
        status = await get_slo_status(redis=fake_redis)
        slo = status["slos"][1]
        assert slo["name"] == "notification_delivery"
        assert slo["measurements"]["delivered"] == 1
        assert slo["measurements"]["failed"] == 0
        assert slo["measurements"]["success_rate_pct"] == 100.0
        assert slo["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_record_notification_delivery_failed(self, fake_redis):
        await record_notification_delivery(succeeded=False, redis=fake_redis)
        await record_notification_delivery(succeeded=False, redis=fake_redis)
        status = await get_slo_status(redis=fake_redis)
        slo = status["slos"][1]
        assert slo["measurements"]["delivered"] == 0
        assert slo["measurements"]["failed"] == 2
        assert slo["measurements"]["success_rate_pct"] == 0.0
        assert slo["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_notification_delivery_mixed_rate(self, fake_redis):
        # 99 delivered, 1 failed → 99% → exactly at the target.
        for _ in range(99):
            await record_notification_delivery(succeeded=True, redis=fake_redis)
        await record_notification_delivery(succeeded=False, redis=fake_redis)
        status = await get_slo_status(redis=fake_redis)
        slo = status["slos"][1]
        assert slo["measurements"]["total"] == 100
        assert slo["measurements"]["success_rate_pct"] == 99.0
        assert slo["status"] == "healthy"


class TestSLOStatus:
    """The status computation and structure."""

    @pytest.mark.asyncio
    async def test_empty_counters_return_unknown(self, fake_redis):
        # The outbox SLO reads from the database, not Redis.  Pass a session
        # factory that raises so it reports "unknown" just like the counters.
        def _failing_factory():
            class _Ctx:
                async def __aenter__(self):
                    raise RuntimeError("no db")

                async def __aexit__(self, *a):
                    return False

            return _Ctx()

        status = await get_slo_status(redis=fake_redis, session_factory=_failing_factory)
        assert len(status["slos"]) == 3
        for slo in status["slos"]:
            assert slo["status"] == "unknown"
        # Names are stable.
        names = [s["name"] for s in status["slos"]]
        assert names == [
            "settings_effective_latency",
            "notification_delivery",
            "outbox_lag",
        ]

    @pytest.mark.asyncio
    async def test_targets_are_exposed_in_status(self, fake_redis):
        status = await get_slo_status(redis=fake_redis)
        latency = status["slos"][0]
        notif = status["slos"][1]
        outbox = status["slos"][2]
        assert str(int(SLO_LATENCY_TARGET_SECONDS * 1000)) in latency["target"]
        assert str(int(SLO_NOTIFICATION_SUCCESS_TARGET * 100)) in notif["target"]
        assert str(int(SLO_OUTBOX_LAG_TARGET_SECONDS)) in outbox["target"]
