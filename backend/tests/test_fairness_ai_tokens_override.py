"""§144 — an operator can raise the daily AI token budget (FAIRNESS_AI_TOKENS_DAILY).

A deployment still being built, with no real customers and heavy live measurement, spends its own
2M-token day in a few dozen questions. The override lets the operator lift that without touching
Redis. It must be safe by construction: a typo can never switch the gate off or lock everyone out,
and only the AI token budget can be moved.
"""

from __future__ import annotations

import uuid

import pytest

from app.core import fairness
from app.core.fairness import DEFAULT_DAILY_BUDGETS, ResourceType, daily_limit

ENV = "FAIRNESS_AI_TOKENS_DAILY"
AI = ResourceType.AI_TOKENS
DEFAULT = DEFAULT_DAILY_BUDGETS[AI]


def test_without_the_variable_the_default_applies(monkeypatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    assert daily_limit(AI) == DEFAULT == 2_000_000


def test_a_positive_number_raises_the_limit(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "50000000")
    assert daily_limit(AI) == 50_000_000


def test_surrounding_whitespace_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "  5000000 \n")
    assert daily_limit(AI) == 5_000_000


@pytest.mark.parametrize("bad", ["", "   ", "abc", "-5", "0", "1.5", "2e6", "1,000", "٥٠٠"])
def test_anything_unusable_falls_back_to_the_default(monkeypatch, bad) -> None:
    """A typo must not disable the gate (0 / negative) or lock every tenant out."""
    monkeypatch.setenv(ENV, bad)
    assert daily_limit(AI) == DEFAULT


def test_the_other_budgets_are_never_overridden(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "50000000")
    for resource in ResourceType:
        if resource is not AI:
            assert daily_limit(resource) == DEFAULT_DAILY_BUDGETS[resource]


async def test_consume_honours_the_raised_limit(monkeypatch) -> None:
    from fakeredis.aioredis import FakeRedis

    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(fairness, "get_redis", lambda: fake)
    tenant = uuid.uuid4()
    key = fairness._budget_key(tenant, AI)
    await fake.set(key, 2_044_354)  # the demo store's real counter: over the default

    monkeypatch.delenv(ENV, raising=False)
    assert await fairness.consume(tenant, AI, units=1000) is False

    monkeypatch.setenv(ENV, "50000000")
    assert await fairness.consume(tenant, AI, units=1000) is True


async def test_usage_and_check_report_the_raised_limit(monkeypatch) -> None:
    from fakeredis.aioredis import FakeRedis

    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(fairness, "get_redis", lambda: fake)
    tenant = uuid.uuid4()
    await fake.set(fairness._budget_key(tenant, AI), 2_044_354)
    monkeypatch.setenv(ENV, "10000000")

    usage = (await fairness.get_usage(tenant))[AI.value]
    assert usage["limit"] == 10_000_000
    assert usage["remaining"] == 10_000_000 - 2_044_354

    check = await fairness.check_budget(tenant, AI, units=500_000)
    assert check.limit == 10_000_000
    assert check.allowed is True
