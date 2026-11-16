"""The owner's assistant shows how long it thought, its thinking per round, and why it was slow.

Everything here is MEASURED: the model's thinking comes from the provider's own response (the Vercel
gateway's ``reasoning`` field, which Qwen fills, checked against the live endpoint), each round is
timed around the real provider request inside the real gateway, and each tool around its handler.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.chat import trace as trace_module
from app.modules.ai.chat.progress import with_progress
from app.modules.ai.chat.trace import REASONING_MAX_CHARS, clip_reasoning, explain
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import AIChatMessage, AIChatThread
from app.modules.ai.providers import _answer_text, _reasoning_text
from tests.test_si_agent import _seed

# ── the thinking is read, and never becomes the answer ────────────────────────────────────────────


def test_the_gateway_reasoning_field_is_read():
    # the exact shape the live Vercel gateway returned for alibaba/qwen3.8-omni-flash
    msg = {"content": "17 × 23 = 391", "reasoning": "17*23 = 340+51 = 391", "reasoning_details": []}
    assert _reasoning_text(msg) == "17*23 = 340+51 = 391"
    assert _answer_text(msg["content"]) == "17 × 23 = 391"


def test_dashscope_reasoning_content_is_read():
    assert _reasoning_text({"content": "x", "reasoning_content": "  think  "}) == "think"


def test_reasoning_details_parts_are_joined():
    msg = {
        "content": "x",
        "reasoning_details": [{"type": "reasoning.text", "text": "a"}, {"text": "b"}],
    }
    assert _reasoning_text(msg) == "ab"


def test_inline_think_blocks_are_the_thinking_and_stay_out_of_the_answer():
    content = "<think>check the sales first</think>المبيعات 100"
    assert _reasoning_text({"content": content}) == "check the sales first"
    assert _answer_text(content) == "المبيعات 100"


def test_no_thinking_is_none():
    assert _reasoning_text({"content": "just the answer"}) is None
    assert _reasoning_text({"content": None, "reasoning": "   "}) is None


def test_a_long_thinking_is_cut_and_marked_cut():
    text, cut = clip_reasoning("x" * (REASONING_MAX_CHARS + 50))
    assert len(text) == REASONING_MAX_CHARS and cut is True
    assert clip_reasoning("short") == ("short", False)
    assert clip_reasoning(None) == (None, False)


# ── the timings and the reasons ───────────────────────────────────────────────────────────────────


def _model(i, ms, out=100, purpose="answer", ok=True, at=0):
    return [
        {"id": i, "kind": "model", "phase": "start", "at_ms": at, "purpose": purpose},
        {
            "id": i,
            "kind": "model",
            "phase": "end",
            "at_ms": at + ms,
            "ms": ms,
            "tokens_in": 3000,
            "tokens_out": out,
            "ok": ok,
            "reasoning": "r",
        },
    ]


def _tool(i, ms, tool="si_metric", args=None, step="بقرا المبيعات"):
    return [
        {
            "id": i,
            "kind": "tool",
            "phase": "start",
            "at_ms": 0,
            "tool": tool,
            "args": args or {},
            "step": step,
        },
        {"id": i, "kind": "tool", "phase": "end", "at_ms": ms, "ms": ms, "ok": True},
    ]


def test_a_quick_answer_has_its_split_and_no_reason():
    s = explain(_model(1, 4000) + _tool(2, 300) + _model(3, 5000), total_ms=10000)
    assert (s["model_ms"], s["tools_ms"], s["other_ms"], s["rounds"], s["tool_calls"]) == (
        9000,
        300,
        700,
        2,
        1,
    )
    assert s["tokens_out"] == 200
    assert s["reasons"] == []


def test_the_same_read_twice_is_named():
    ev = _tool(1, 100, args={"mode": "value", "days": 30}) + _tool(
        2, 100, args={"days": 30, "mode": "value"}
    )
    assert any("نفس البيانات بالظبط 2" in r for r in explain(ev, 1000)["reasons"])


def test_the_same_source_three_times_with_different_asks_is_named():
    ev = sum((_tool(i, 50, args={"days": d}) for i, d in ((1, 7), (2, 30), (3, 90))), [])
    reasons = explain(ev, 500)["reasons"]
    assert any("3 مرات بطلبات مختلفة" in r for r in reasons)
    assert not any("بالظبط" in r for r in reasons)


def test_a_rewrite_and_a_fill_are_named_with_their_cost():
    reasons = explain(
        _model(1, 4000) + _model(2, 6200, purpose="rewrite") + _model(3, 3000, purpose="fill_gap"),
        14000,
    )["reasons"]
    assert any("اترفض في مراجعة الأرقام" in r and "6.2" in r for r in reasons)
    assert any("فاتكمّل" in r and "3.0" in r for r in reasons)


def test_a_long_write_is_told_apart_from_a_slow_provider():
    long_write = explain(_model(1, 30000, out=1500), 30000)["reasons"]
    assert any("كتب كتير" in r for r in long_write) and not any("مزوّد" in r for r in long_write)
    slow = explain(_model(1, 12000, out=50), 12000)["reasons"]
    assert any("مزوّد النموذج" in r for r in slow)
    # 8 s for 400 tokens is the length (20 ms a token), not the provider
    assert not any("مزوّد" in r for r in explain(_model(1, 8000, out=400), 8000)["reasons"])


def test_many_rounds_a_failed_round_a_slow_read_and_time_outside_are_named():
    ev = (
        _model(1, 3000)
        + _model(2, 3000)
        + _model(3, 3000, ok=False)
        + _model(4, 3000)
        + _tool(5, 2500)
    )
    reasons = explain(ev, 20000)["reasons"]
    assert any("4 جولات" in r for r in reasons)
    assert any("فشلت عند المزوّد" in r for r in reasons)
    assert any("بقرا المبيعات" in r and "2.5" in r for r in reasons)
    assert any("برّه النموذج" in r and "5.5" in r for r in reasons)


def test_an_unfinished_event_is_not_counted():
    ev = _model(1, 4000) + [{"id": 2, "kind": "model", "phase": "start", "at_ms": 4000}]
    assert explain(ev, 9000)["rounds"] == 1


# ── written on the answer, through the real gateway and the real tool wrapper ─────────────────────


@pytest.fixture
def trace_on_the_test_session(db, monkeypatch):
    class _Shared:
        async def execute(self, *a, **k):
            return await db.execute(*a, **k)

        async def commit(self):
            await db.flush()

    class _Ctx:
        async def __aenter__(self):
            return _Shared()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(trace_module.core_db, "get_sessionmaker", lambda: lambda: _Ctx())

    async def _bind(*a, **k):
        return None

    monkeypatch.setattr(trace_module, "bind_tenant", _bind)
    return db


async def _generating_row(db, tenant_ctx, status="generating"):
    agent = await _seed(db, tenant_ctx.tenant_id)
    thread = AIChatThread(
        tenant_id=tenant_ctx.tenant_id,
        agent_id=agent.id,
        title="t",
        created_by_user_id=tenant_ctx.user.id,
    )
    db.add(thread)
    await db.flush()
    row = AIChatMessage(
        tenant_id=tenant_ctx.tenant_id,
        thread_id=thread.id,
        sequence_no=2,
        role="assistant",
        status=status,
        content="",
    )
    db.add(row)
    await db.flush()
    return row


class _Settings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "k"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "m"


async def _gateway_call(db, tenant_id, body, *, purpose=None):
    def handler(request):
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if purpose:
            with trace_module.purpose(purpose):
                return await AIGateway().chat(
                    db,
                    tenant_id,
                    alias="fast",
                    messages=[{"role": "user", "content": "q"}],
                    _client=client,
                )
        return await AIGateway().chat(
            db, tenant_id, alias="fast", messages=[{"role": "user", "content": "q"}], _client=client
        )


async def test_a_real_gateway_call_writes_its_round_with_thinking_and_tokens(
    db, tenant_ctx, monkeypatch, trace_on_the_test_session
):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _Settings())
    row = await _generating_row(db, tenant_ctx)
    body = {
        "model": "m",
        "choices": [{"message": {"content": "تمام", "reasoning": "fikr"}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4},
    }
    with trace_module.tracing(tenant_ctx.tenant_id, row.id):
        result = await _gateway_call(db, tenant_ctx.tenant_id, body)
        await _gateway_call(db, tenant_ctx.tenant_id, body, purpose="rewrite")
    assert result.content == "تمام" and result.reasoning == "fikr"
    await db.refresh(row)
    starts = [e for e in row.trace if e["phase"] == "start"]
    ends = [e for e in row.trace if e["phase"] == "end"]
    assert [e["id"] for e in starts] == [1, 2] and [e["id"] for e in ends] == [1, 2]
    assert [e["purpose"] for e in starts] == ["answer", "rewrite"]
    end = ends[0]
    assert end["reasoning"] == "fikr" and end["reasoning_cut"] is False
    assert (end["tokens_in"], end["tokens_out"], end["ok"], end["answered"]) == (9, 4, True, True)
    assert isinstance(end["ms"], int) and end["ms"] >= 0


async def test_outside_a_chat_turn_the_gateway_writes_nothing(
    db, tenant_ctx, monkeypatch, trace_on_the_test_session
):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _Settings())
    row = await _generating_row(db, tenant_ctx)
    body = {"model": "m", "choices": [{"message": {"content": "x", "reasoning": "r"}}], "usage": {}}
    await _gateway_call(db, tenant_ctx.tenant_id, body)
    await db.refresh(row)
    assert row.trace is None


async def test_a_failed_round_is_written_as_failed(
    db, tenant_ctx, monkeypatch, trace_on_the_test_session
):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _Settings())
    row = await _generating_row(db, tenant_ctx)

    def handler(request):
        return httpx.Response(400, json={"error": "bad"})

    with trace_module.tracing(tenant_ctx.tenant_id, row.id):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ExternalProviderError):
                await AIGateway().chat(
                    db,
                    tenant_ctx.tenant_id,
                    alias="fast",
                    messages=[{"role": "user", "content": "q"}],
                    _client=client,
                )
    await db.refresh(row)
    end = [e for e in row.trace if e["phase"] == "end"][0]
    assert end["ok"] is False and end["reasoning"] is None


async def test_a_tool_is_timed_with_its_read_and_a_failing_tool_is_marked(
    db, tenant_ctx, trace_on_the_test_session
):
    row = await _generating_row(db, tenant_ctx)

    async def handler(*, mode: str, days: int = 30, tenant_id=None):
        if days == 99:
            raise RuntimeError("boom")
        return {"ok": True}

    wrapped = with_progress("si_metric", handler)
    with trace_module.tracing(tenant_ctx.tenant_id, row.id):
        assert await wrapped(mode="value", days=7, tenant_id="t") == {"ok": True}
        with pytest.raises(RuntimeError):
            await wrapped(mode="value", days=99)
    await db.refresh(row)
    starts = [e for e in row.trace if e["phase"] == "start"]
    ends = [e for e in row.trace if e["phase"] == "end"]
    assert starts[0]["tool"] == "si_metric" and starts[0]["args"] == {"mode": "value", "days": 7}
    assert starts[0]["step"]  # the plain Arabic line of the read
    assert [e["ok"] for e in ends] == [True, False]


async def test_the_summary_is_appended_from_what_was_written(
    db, tenant_ctx, monkeypatch, trace_on_the_test_session
):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _Settings())
    row = await _generating_row(db, tenant_ctx)
    body = {
        "model": "m",
        "choices": [{"message": {"content": "x"}}],
        "usage": {"completion_tokens": 7},
    }
    with trace_module.tracing(tenant_ctx.tenant_id, row.id):
        await _gateway_call(db, tenant_ctx.tenant_id, body)
        await trace_module.finish()
    await db.refresh(row)
    summary = row.trace[-1]
    assert summary["kind"] == "summary" and summary["rounds"] == 1 and summary["tokens_out"] == 7
    assert summary["total_ms"] >= summary["model_ms"]


async def test_nothing_lands_on_an_answer_that_is_already_done(
    db, tenant_ctx, trace_on_the_test_session
):
    row = await _generating_row(db, tenant_ctx, status="completed")
    with trace_module.tracing(tenant_ctx.tenant_id, row.id):
        await trace_module.start("model")
    await db.refresh(row)
    assert row.trace is None


async def test_a_database_that_refuses_costs_the_trace_never_the_answer(
    db, tenant_ctx, monkeypatch
):
    row = await _generating_row(db, tenant_ctx)

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(trace_module.core_db, "get_sessionmaker", broken)
    with trace_module.tracing(tenant_ctx.tenant_id, row.id):
        event_id = await trace_module.start("model")
        await trace_module.end(event_id, "model", 5)
        await trace_module.finish()
    assert event_id == 1


# ── the rewrites name themselves, so a slow answer can say it was written twice ───────────────────


async def test_a_rewrite_and_a_fill_are_labelled_where_the_real_functions_call_the_model(
    monkeypatch,
):
    import uuid
    from types import SimpleNamespace

    from app.modules.ai.agents.sales_intelligence import coverage
    from app.modules.ai.providers import ChatCompletionResult

    agent = SimpleNamespace(
        id=uuid.uuid4(),
        kind="sales_intelligence",
        model="fast",
        system_prompt="analyze",
        temperature=0.2,
        max_output_tokens=200,
    )

    class _Session:
        async def get(self, model, obj_id):
            return agent

    seen: list[str] = []

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen.append(trace_module._PURPOSE.get())
        return ChatCompletionResult(
            content="المبيعات قيمة الطلبات الموضوعة: 5",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    common = dict(
        agent_id=agent.id,
        run_id=None,
        history=None,
        draft="عدد الطلبات: 5",
        evidence={"facts": [{"metric": "orders_placed", "value": 5}]},
        allowed_numbers={"5"},
        findings=[],
        tool_calls_made=[],
    )
    await coverage.regenerate_on_coverage_gap(
        _Session(), uuid.uuid4(), question="كام مبيعات وكام طلبات؟", **common
    )
    await coverage.regenerate_on_rejected_answer(
        _Session(),
        uuid.uuid4(),
        question="كام؟",
        problems=[f"{coverage._FREE_NUMBER_PREFIX} 17"],
        **common,
    )
    assert seen == ["fill_gap", "rewrite"]
    # and the label does not leak into the next, ordinary call
    assert trace_module._PURPOSE.get() == "answer"


# ── every reason has a stable code, and the shop report counts causes across answers ──────────────


def test_each_reason_carries_its_code_in_the_same_order():
    from app.modules.ai.chat.trace import CODE_TEXT

    ev = (
        _tool(1, 2500, args={"d": 1})
        + _tool(2, 10, args={"d": 1})
        + _model(3, 3000)
        + _model(4, 3000, purpose="rewrite")
        + _model(5, 3000, out=1500)
        + _model(6, 12000, out=10, ok=False)
    )
    s = explain(ev, 40000)
    assert len(s["codes"]) == len(s["reasons"])
    assert set(s["codes"]) <= set(CODE_TEXT)
    assert {
        "repeat_same",
        "rewrite",
        "long_write",
        "slow_provider",
        "failed_round",
        "many_rounds",
        "slow_read",
        "other_time",
    } <= set(s["codes"])


def _summary(total, model=0, rounds=1, codes=(), reasons=()):
    return [
        {
            "id": 0,
            "kind": "summary",
            "total_ms": total,
            "model_ms": model,
            "tools_ms": 0,
            "other_ms": 0,
            "rounds": rounds,
            "codes": list(codes),
            "reasons": list(reasons),
        }
    ]


def test_the_report_counts_causes_per_answer_and_lists_the_slowest_first():
    from app.modules.ai.chat.trace import report

    r = report(
        [
            ("س1", _summary(10000, 8000, 2, ["rewrite"], ["اتكتب تاني"])),
            ("س2", _summary(40000, 30000, 5, ["many_rounds", "repeat_same", "repeat_same"])),
            ("س3", _summary(20000, 15000, 3, ["rewrite", "unknown_code"])),
            ("قديم", None),
            ("بلا ملخص", _model(1, 5)),
        ]
    )
    assert (r["answers"], r["untraced"]) == (3, 2)
    assert r["median_total_ms"] == 20000 and r["avg_total_ms"] == 23333
    assert r["avg_rounds"] == 3.33
    # a code counts once per answer; an unknown code is not reported
    assert [(c["code"], c["answers"]) for c in r["causes"]] == [
        ("rewrite", 2),
        ("many_rounds", 1),
        ("repeat_same", 1),
    ]
    assert [s["question"] for s in r["slowest"]] == ["س2", "س3", "س1"]
    assert r["slowest"][2]["reasons"] == ["اتكتب تاني"]


def test_an_empty_report_is_zeros_not_an_error():
    from app.modules.ai.chat.trace import report

    r = report([])
    assert (
        r["answers"] == 0 and r["median_total_ms"] == 0 and r["causes"] == [] and r["slowest"] == []
    )


async def test_the_report_reads_only_what_the_caller_may_see(db, tenant_ctx):
    import uuid

    from app.modules.ai.chat import service
    from app.modules.identity.models import User

    agent = await _seed(db, tenant_ctx.tenant_id)
    staff = User(email=f"staff-{uuid.uuid4().hex[:8]}@test.local", password_hash="x", full_name="S")
    db.add(staff)
    await db.flush()
    other_user = staff.id

    async def thread_with(owner_id, question, total):
        th = AIChatThread(
            tenant_id=tenant_ctx.tenant_id,
            agent_id=agent.id,
            title="t",
            created_by_user_id=owner_id,
        )
        db.add(th)
        await db.flush()
        db.add(
            AIChatMessage(
                tenant_id=tenant_ctx.tenant_id,
                thread_id=th.id,
                sequence_no=1,
                role="user",
                status="completed",
                content=question,
            )
        )
        db.add(
            AIChatMessage(
                tenant_id=tenant_ctx.tenant_id,
                thread_id=th.id,
                sequence_no=2,
                role="assistant",
                status="completed",
                content="رد",
                trace=_summary(total),
            )
        )
        await db.flush()

    await thread_with(tenant_ctx.user.id, "سؤالي", 5000)
    await thread_with(other_user, "سؤال غيري", 9000)

    class _Ctx:
        tenant_id = tenant_ctx.tenant_id
        user = tenant_ctx.user
        role = "staff"
        is_owner = False
        permission_codes = {"analytics:read"}

    from app.modules.ai.chat import service as svc

    original = svc._is_tenant_owner
    try:
        svc._is_tenant_owner = lambda ctx: False
        mine = await service.timing_report(db, _Ctx())
        svc._is_tenant_owner = lambda ctx: True
        everyone = await service.timing_report(db, _Ctx())
    finally:
        svc._is_tenant_owner = original
    assert [s["question"] for s in mine["slowest"]] == ["سؤالي"]
    assert sorted(s["question"] for s in everyone["slowest"]) == ["سؤال غيري", "سؤالي"]
