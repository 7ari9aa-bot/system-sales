"""AI domain — agents, tools, prompts, model_configs, memories, knowledge,
agent_runs, tool_calls, model_calls, ai_usage.

Hard rule: the LLM never touches SQL. Tool calls go through tool policies and
application services only.
"""

# P0-5: Ensure canonical agent provisioning hook is registered at application startup
import app.modules.ai.core.provisioning as _provisioning  # noqa: F401

# The console spend surface self-registers into core.console_spending here:
# package load IS the wiring — without it the module is orphaned (the
# dead-modules guard) and the owner console reads zero rows in silence.
import app.modules.ai.spend_read as _console_spend_registration  # noqa: F401
