"""A model that guesses a metric name gets the valid names back, not a generic failure.

The model is a per-shop setting and may be any ordinary model, so it will sometimes ask for a
metric the registry does not have (``revenue``). The runner shows the model only the message of
a DomainError; any other exception becomes "the tool failed unexpectedly", so the model repeats
the same guess until the tool budget is gone. The tools must therefore refuse an unknown metric
with a ValidationError that names what is available.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.modules.ai.agents.sales_intelligence.tools import (
    _si_breakdown,
    _si_compare_periods,
    _si_explain_metric,
    _si_get_metric,
)
from app.modules.analytics.compiler import computable_metric_names
from app.modules.analytics.semantic import all_metrics

CALLS = {
    "get_metric": lambda db, t: _si_get_metric(db, t, metric_name="revenue"),
    "compare_periods": lambda db, t: _si_compare_periods(db, t, metric_name="revenue"),
    "breakdown": lambda db, t: _si_breakdown(db, t, metric_name="revenue", dimension="channel"),
    "explain_metric": lambda db, t: _si_explain_metric(db, t, metric_name="revenue"),
}


@pytest.mark.parametrize("tool", sorted(CALLS))
async def test_an_unknown_metric_is_refused_with_the_valid_names(tool, db, tenant_ctx):
    with pytest.raises(ValidationError) as caught:
        await CALLS[tool](db, tenant_ctx.tenant_id)

    message = str(caught.value)
    assert "revenue" in message
    if tool == "explain_metric":
        # explaining reads the definition, so every registered name is a valid choice
        names = set(all_metrics())
    else:
        # computing tools must list only what can be computed: offering aov/net_revenue as
        # "valid" sends the model straight into the second refusal
        names = set(computable_metric_names())
        for derived in set(all_metrics()) - names:
            assert derived not in message, f"{derived} is offered but cannot be computed"
    for name in names:
        assert name in message, f"{name} missing from the hint the model reads"


async def test_a_known_metric_still_works(db, tenant_ctx):
    out = await _si_get_metric(db, tenant_ctx.tenant_id, metric_name="orders_placed", days=30)
    assert out["facts"]


@pytest.mark.parametrize("composite", ["aov", "net_revenue"])
@pytest.mark.parametrize("tool", ["get_metric", "compare_periods", "breakdown"])
async def test_a_composite_metric_is_refused_with_the_computable_names(
    tool, composite, db, tenant_ctx
):
    # aov and net_revenue are in the registry but have no compiled statement; the compiler's
    # UnsupportedFilter is a bare Exception, which the model hears as "failed unexpectedly".
    calls = {
        "get_metric": lambda: _si_get_metric(db, tenant_ctx.tenant_id, metric_name=composite),
        "compare_periods": lambda: _si_compare_periods(
            db, tenant_ctx.tenant_id, metric_name=composite
        ),
        "breakdown": lambda: _si_breakdown(
            db, tenant_ctx.tenant_id, metric_name=composite, dimension="channel"
        ),
    }
    with pytest.raises(ValidationError) as caught:
        await calls[tool]()

    message = str(caught.value)
    assert composite in message
    assert "orders_placed" in message  # a computable name is offered
    # the other composite is NOT offered as an alternative the model could pick next
    other = "net_revenue" if composite == "aov" else "aov"
    assert f", {other}" not in message and f": {other}" not in message


async def test_explaining_a_composite_metric_is_still_allowed(db, tenant_ctx):
    # explain_metric reads the definition, it does not compute, so a composite is explainable.
    out = await _si_explain_metric(db, tenant_ctx.tenant_id, metric_name="aov")
    assert out["status"] == "ok"


async def test_an_unsupported_combination_reaches_the_model_as_a_readable_refusal(db, tenant_ctx):
    # collected_revenue cannot be split by channel. The compiler says so with a bare
    # UnsupportedFilter, which the runner turns into "tool failed unexpectedly"; the registered
    # tool must turn it into a DomainError whose message the model is shown.
    from app.modules.ai.agents.sales_intelligence.tools import register_si_tools
    from app.modules.ai.tools import get_tool

    register_si_tools()
    spec = get_tool("si_breakdown")

    with pytest.raises(ValidationError) as caught:
        await spec.handler(
            db, tenant_ctx.tenant_id, metric_name="collected_revenue", dimension="channel"
        )

    assert "collected_revenue" in str(caught.value)
    assert "channel" in str(caught.value)


async def test_every_registered_si_tool_explains_unsupported_requests():
    from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS, register_si_tools
    from app.modules.ai.tools import get_tool

    register_si_tools()
    unwrapped = [
        n for n in SI_TOOLS if not getattr(get_tool(n).handler, "explains_unsupported", False)
    ]
    assert unwrapped == []


async def test_the_wrapper_does_not_swallow_a_real_failure():
    # Only UnsupportedFilter is a "you asked for something unsupported" outcome. A genuine bug
    # must stay an unexpected failure so it is logged and fixed, not shown as advice.
    from app.modules.ai.agents.sales_intelligence.tools import _explain_unsupported

    async def broken(session, tenant_id, **kwargs):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _explain_unsupported(broken)(None, None)
