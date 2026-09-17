"""AI domain — agents, tools, prompts, model_configs, memories, knowledge,
agent_runs, tool_calls, model_calls, ai_usage.

Hard rule: the LLM never touches SQL. Tool calls go through tool policies and
application services only.
"""
