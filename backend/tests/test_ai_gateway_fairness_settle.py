"""The daily token counter is charged an estimate BEFORE a model call; the gateway settles it after.

The estimate (prompt chars / 4 plus 1024 reply tokens) is high on purpose, so without a settle a
question that really used ~19k tokens in four calls was billed far more and a store reached its
daily budget after ~100 questions. These tests pin the settle: a call gives back what it did not
use, a failed or refused one gives back everything, and a provider that reports no usage keeps the
estimate (unknown is not free, or a silent provider would open the budget wide).
"""

from __future__ import annotations

import httpx
import pytest
from fakeredis.aioredis import FakeRedis

from app.core import fairness
from app.core.errors import ExternalProviderError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.budget import AIBudgetExhaustedError
from app.modules.ai.gateway import AIGateway

AI = fairness.ResourceType.AI_TOKENS
MESSAGES = [{"role": "user", "content": "hi"}]
ESTIMATE = len(str(MESSAGES)) // 4 + 300  # max_tokens=300 below


class _Settings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "gpt-test"


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(fairness, "get_redis", lambda: fake)
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _Settings())
    return fake


def _reply(usage: dict | None) -> dict:
    body: dict = {
        "model": "gpt-test",
        "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


async def _call(db, tenant_id, handler):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await AIGateway().chat(
            db, tenant_id, alias="fast", messages=MESSAGES, max_tokens=300, _client=client
        )


async def _counter(redis, tenant_id) -> int:
    return int(await redis.get(fairness._budget_key(tenant_id, AI)) or 0)


async def test_a_call_is_billed_what_it_used_not_the_estimate(db, tenant_ctx, redis):
    handler = lambda r: httpx.Response(  # noqa: E731
        200, json=_reply({"prompt_tokens": 9, "completion_tokens": 4})
    )
    await _call(db, tenant_ctx.tenant_id, handler)
    assert await _counter(redis, tenant_ctx.tenant_id) == 13


async def test_a_call_that_used_more_than_the_estimate_is_not_refunded(db, tenant_ctx, redis):
    handler = lambda r: httpx.Response(  # noqa: E731
        200, json=_reply({"prompt_tokens": 5000, "completion_tokens": 900})
    )
    await _call(db, tenant_ctx.tenant_id, handler)
    # The charge stays at the estimate: settling never bills EXTRA, it only gives back.
    assert await _counter(redis, tenant_ctx.tenant_id) == ESTIMATE


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 0, "completion_tokens": 0}])
async def test_a_provider_that_reports_no_usage_keeps_the_estimate(db, tenant_ctx, redis, usage):
    handler = lambda r: httpx.Response(200, json=_reply(usage))  # noqa: E731
    await _call(db, tenant_ctx.tenant_id, handler)
    assert await _counter(redis, tenant_ctx.tenant_id) == ESTIMATE


async def test_a_failed_call_is_not_billed(db, tenant_ctx, redis):
    handler = lambda r: httpx.Response(500, json={"error": "kaput"})  # noqa: E731
    with pytest.raises(ExternalProviderError):
        await _call(db, tenant_ctx.tenant_id, handler)
    assert await _counter(redis, tenant_ctx.tenant_id) == 0


async def test_a_call_refused_for_a_spent_budget_leaves_the_counter_where_it_was(
    db, tenant_ctx, redis, monkeypatch
):
    monkeypatch.setattr(fairness, "daily_limit", lambda resource: 100)
    await redis.set(fairness._budget_key(tenant_ctx.tenant_id, AI), 100)
    handler = lambda r: httpx.Response(  # noqa: E731
        200, json=_reply({"prompt_tokens": 9, "completion_tokens": 4})
    )
    with pytest.raises(AIBudgetExhaustedError):
        await _call(db, tenant_ctx.tenant_id, handler)
    assert await _counter(redis, tenant_ctx.tenant_id) == 100


async def test_settling_never_extends_the_window_or_goes_below_zero(redis):
    tenant = __import__("uuid").uuid4()
    key = fairness._budget_key(tenant, AI)
    await redis.set(key, 500, ex=100)

    await fairness.refund(tenant, AI, units=200)
    assert int(await redis.get(key)) == 300
    assert 0 < await redis.ttl(key) <= 100  # a refund does not restart the 24h window

    await fairness.refund(tenant, AI, units=10_000)  # more than is left: clamp, never negative
    assert int(await redis.get(key)) == 0

    await fairness.refund(tenant, AI, units=0)
    await fairness.refund(tenant, AI, units=-5)
    assert int(await redis.get(key)) == 0
