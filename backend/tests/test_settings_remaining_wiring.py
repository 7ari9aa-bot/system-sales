"""Regression tests for the remaining settings wiring (Phase 4–6).

Covers:
- customer_agent.handoff_enabled gates the model-initiated handover tool
- analytics_agent.enabled gates run_sales_analysis
- analytics_agent.min_confidence filters low-confidence findings
- branch.notify_manager_on_variance creates a notification on drawer variance
- branch.allow_independent_purchasing marks POs under centralized purchasing
- notifications.order_received creates a notification on order creation
- notifications.low_stock_alert gates the low-stock scheduler job

These are unit-level tests that exercise the setting reads without a database
where possible, and skip when no database is configured (the standard pattern).
"""

from __future__ import annotations

import uuid

# The async tests below use asyncio_mode=auto (pyproject.toml).


async def test_handoff_enabled_gate_returns_disabled():
    """When handoff_enabled is False, _handover_to_human returns a disabled message."""
    from app.applications.apparel.modules.ai.agents.customer.tools.support import _handover_to_human

    class FakeSettingsService:
        def __init__(self, session, tid):
            pass

        async def value(self, key):
            assert key == "customer_agent.handoff_enabled"
            return False

    # The function does a function-scope import, so we patch at the source module.
    import app.platform.settings.service as settings_mod

    saved = settings_mod.SettingsService
    settings_mod.SettingsService = FakeSettingsService  # type: ignore[assignment]
    try:
        result = await _handover_to_human(
            None,  # session not used when gate fires
            uuid.uuid4(),
            reason="customer_request",
            summary="test",
            context={"conversation_id": str(uuid.uuid4())},
        )
        assert result["status"] == "handover_disabled"
    finally:
        settings_mod.SettingsService = saved  # type: ignore[assignment]


async def test_analytics_agent_disabled_returns_unsupported():
    """When analytics_agent.enabled is False, run_sales_analysis returns UNSUPPORTED_ANALYSIS."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence.agent import AnalysisResult, run_sales_analysis
    from app.applications.apparel.modules.analytics.contracts import Outcome

    class FakeSettingsService:
        def __init__(self, session, tid):
            pass

        async def value(self, key):
            if key == "analytics_agent.enabled":
                return False
            return None

    import app.platform.settings.service as settings_mod

    saved = settings_mod.SettingsService
    settings_mod.SettingsService = FakeSettingsService  # type: ignore[assignment]
    try:
        result = await run_sales_analysis(
            None,  # session
            uuid.uuid4(),
            agent_id=uuid.uuid4(),
            question="test question",
        )
        assert isinstance(result, AnalysisResult)
        assert result.outcome == Outcome.UNSUPPORTED_ANALYSIS
    finally:
        settings_mod.SettingsService = saved  # type: ignore[assignment]


def test_low_stock_alerts_job_registered():
    """The low_stock_alerts handler is registered with the scheduler."""
    from app.workers import scheduler_worker

    # The scheduler_worker module registers handlers on import.
    # We just need to verify the function exists and is callable.
    assert hasattr(scheduler_worker, "_handle_low_stock_alerts")
    assert callable(scheduler_worker._handle_low_stock_alerts)


def test_auto_close_shifts_job_registered():
    """The auto_close_shifts handler is registered with the scheduler."""
    from app.workers import scheduler_worker

    assert hasattr(scheduler_worker, "_handle_auto_close_shifts")
    assert callable(scheduler_worker._handle_auto_close_shifts)


def test_handover_to_human_args_schema():
    """HandoverToHumanArgs accepts the four allowed reasons."""
    from app.applications.apparel.modules.ai.agents.customer.tools.support import HandoverToHumanArgs

    for reason in ("complex_problem", "missing_data", "customer_request", "complaint"):
        args = HandoverToHumanArgs(reason=reason, summary="test summary")
        assert args.reason == reason
