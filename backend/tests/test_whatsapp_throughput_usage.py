"""The send-rate view: what an operator needs to tell a 130429 apart from a real failure.

Meta's cap is 20 messages per second per number. When a send fails with 130429 the first question is
always "are we over the cap, or is something else wrong?", and until now there was nothing to look
at. The view must also refuse to report a fake zero when the limiter is not tracking the number: an
idle number and an unmonitored one are different facts.
"""

from __future__ import annotations

from app.applications.apparel.modules.conversations.gateway import whatsapp_throughput as tp


class _FakeRedis:
    def __init__(self, count: int = 0, *, fail: bool = False) -> None:
        self.count = count
        self.fail = fail
        self.seen: list[str] = []

    async def zcount(self, key: str, _min: int, _max: int) -> int:
        self.seen.append(key)
        if self.fail:
            raise RuntimeError("redis down")
        return self.count


async def test_an_idle_number_shows_full_headroom() -> None:
    usage = await tp.usage("456", client=_FakeRedis(0))

    assert usage["current"] == 0
    assert usage["remaining"] == tp.MESSAGES_PER_SECOND
    assert usage["headroom_percent"] == 100
    assert usage["state"] == "ok"


async def test_a_number_at_the_cap_says_so() -> None:
    usage = await tp.usage("456", client=_FakeRedis(tp.MESSAGES_PER_SECOND))

    assert usage["remaining"] == 0
    assert usage["state"] == "at_cap"


async def test_a_busy_number_is_flagged_before_it_fails() -> None:
    assert (await tp.usage("456", client=_FakeRedis(16)))["state"] == "busy"


async def test_the_budget_read_is_the_one_the_sender_uses() -> None:
    client = _FakeRedis(5)
    await tp.usage("456", client=client)
    # The same key acquire() counts against, otherwise the number shown is a different budget.
    assert client.seen == [f"{tp.KEY_PREFIX}:456"]


async def test_no_limiter_is_reported_as_unknown_not_as_idle(monkeypatch) -> None:
    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: None)
    usage = await tp.usage("456", client=None)

    assert usage["current"] is None
    assert usage["state"] == "unknown"
    assert "not tracking this number" in usage["note"]


async def test_a_broken_limiter_never_breaks_the_status_read() -> None:
    usage = await tp.usage("456", client=_FakeRedis(fail=True))

    assert usage["state"] == "unknown"
    assert usage["current"] is None


def test_the_explanation_covers_both_causes() -> None:
    """A 130429 is not always our pacing: the copy has to say so."""
    import asyncio

    usage = asyncio.run(tp.usage("456", client=_FakeRedis(0)))
    assert "at the cap" in usage["explains_130429"].lower()
    assert "below it" in usage["explains_130429"].lower()
