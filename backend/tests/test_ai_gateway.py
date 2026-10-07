"""AIGateway tests — primary-provider fallback, model_calls recording, budget."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import (
    ExternalProviderError,
    RateLimitExceededError,
    ValidationError,
)
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.gateway import AIGateway, resolve_model_config
from app.modules.ai.models import AIUsage, ModelCall, ModelConfig


class _StubSettings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "gpt-test"


class _EmptySettings:
    ai_provider_primary = ""


def _ok_chat_response(content: str = "pong") -> dict:
    return {
        "model": "gpt-test",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4},
    }


async def test_chat_falls_back_to_primary_settings_and_writes_model_call(
    db, tenant_ctx, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_ok_chat_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AIGateway().chat(
            db,
            tenant_id,
            alias="fast",
            messages=[{"role": "user", "content": "hi"}],
            _client=client,
        )

    assert result.content == "pong"
    assert result.tokens_in == 9
    assert result.tokens_out == 4
    assert captured["url"] == "https://api.test/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"

    rows = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.alias == "fast"
    assert row.provider == "openai"
    assert row.model == "gpt-test"
    assert row.status == "ok"
    assert row.tokens_in == 9
    assert row.tokens_out == 4
    assert row.latency_ms is not None


async def test_chat_prefers_tenant_model_config_row(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        ModelConfig(
            tenant_id=tenant_id,
            alias="fast",
            provider="openai",
            model="cfg-model",
            config={"base_url": "https://cfg.test/v1", "api_key": "cfg-key"},
        )
    )
    await db.flush()

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_ok_chat_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await AIGateway().chat(
            db,
            tenant_id,
            alias="fast",
            messages=[{"role": "user", "content": "hi"}],
            _client=client,
        )

    assert captured["url"] == "https://cfg.test/v1/chat/completions"
    assert captured["auth"] == "Bearer cfg-key"
    row = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert row.model == "cfg-model"


async def test_chat_without_any_model_config_raises(db, tenant_ctx, monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _EmptySettings())
    with pytest.raises(ValidationError, match="fast"):
        await AIGateway().chat(
            db,
            tenant_ctx.tenant_id,
            alias="fast",
            messages=[{"role": "user", "content": "hi"}],
        )
    rows = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_unknown_alias_raises_validation_error(db, tenant_ctx):
    with pytest.raises(ValidationError, match="alias"):
        await resolve_model_config(db, tenant_ctx.tenant_id, "turbo")


async def test_monthly_budget_cap_blocks_chat(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    # Patch the CAP SOURCE, not the old MONTHLY_BUDGET_CAP constant: the default
    # cap is now the `ai_monthly_budget_cap_default` setting (review N-06), so
    # patching the constant no longer changes what `_resolve_cap` returns.
    monkeypatch.setattr(ai_gateway, "_default_cap", lambda: Decimal("1.0"))
    db.add(
        AIUsage(
            tenant_id=tenant_id,
            period_date=date.today(),
            agent_id=None,
            tokens_in=100,
            tokens_out=100,
            cost=5.0,
        )
    )
    await db.flush()

    with pytest.raises(RateLimitExceededError, match="monthly AI budget exceeded"):
        await AIGateway().chat(
            db,
            tenant_id,
            alias="fast",
            messages=[{"role": "user", "content": "hi"}],
        )
    # The budget gate fires before any provider call — nothing recorded.
    rows = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_provider_error_is_recorded_and_raised(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "kaput"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalProviderError):
            await AIGateway().chat(
                db,
                tenant_id,
                alias="fast",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )

    row = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert row.status == "error"
    assert row.tokens_in == 0 and row.tokens_out == 0


async def test_api_key_never_reaches_logs_or_model_call_rows(
    db, tenant_ctx, monkeypatch, caplog
):
    """Routing verdict pin, credential half: `resolve_model_config` is
    deterministic (tenant row, then deployment settings — the tests above
    prove the order), and the credential it resolves is WRITE-ONLY: it rides
    the Authorization header to the provider and appears in no log record and
    in no `model_calls` column. A key that leaks into a log line or a row is
    readable by everyone who can read logs."""
    import logging

    tenant_id = tenant_ctx.tenant_id
    secret = "sk-super-secret-gateway-key-9f8e7d"

    class _KeyedSettings:
        """The deployment stub, with a distinctive key the assertions can hunt for."""

        ai_provider_primary = "openai"
        ai_api_key_primary = secret
        ai_base_url_primary = "https://api.test/v1"
        ai_model_primary = "gpt-test"

    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _KeyedSettings())

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_ok_chat_response())

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await AIGateway().chat(
                db,
                tenant_id,
                alias="fast",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )

    # The key DID reach the provider (that is its one job) ...
    assert captured["auth"] == f"Bearer {secret}"
    # ... and appears nowhere else: not in any log record ...
    leaked_logs = [
        record.getMessage()
        for record in caplog.records
        if secret in record.getMessage()
    ]
    assert leaked_logs == []
    # ... and not in any recorded column of the ModelCall row.
    row = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert secret not in str(row.__dict__)
