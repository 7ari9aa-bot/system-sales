"""Two-prompt composition (pure, no DB) — the base rules and the store voice.

The owner console edits ``system_prompt`` (canonical instructions and
prohibitions) and ``persona_prompt`` (agent name, tone, store name) through
TWO separate controls. The runtime composes base FIRST, persona LAST, and
either half may be empty — the composition is the only place they meet.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.ai.runtime import AgentRunner


def _agent(**overrides) -> SimpleNamespace:
    fields = dict(
        kind="customer",
        system_prompt="القواعد الأساسية: ممنوع البيع.",
        persona_prompt=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_base_only_when_persona_is_absent():
    assert AgentRunner._compose_system_content(_agent()) == "القواعد الأساسية: ممنوع البيع."


def test_persona_composes_after_the_base():
    agent = _agent(persona_prompt="اسمك سارة، بتعمل في محل توت أطفال، كلامك خفيف.")
    composed = AgentRunner._compose_system_content(agent)
    assert composed.startswith("القواعد الأساسية: ممنوع البيع.")
    assert composed.endswith("اسمك سارة، بتعمل في محل توت أطفال، كلامك خفيف.")
    assert "\n\n" in composed


def test_whitespace_persona_is_treated_as_absent():
    agent = _agent(persona_prompt="   \n  ")
    assert AgentRunner._compose_system_content(agent) == "القواعد الأساسية: ممنوع البيع."


def test_base_and_persona_are_both_stripped():
    agent = _agent(system_prompt="  قواعد  ", persona_prompt="  شخصية  ")
    assert AgentRunner._compose_system_content(agent) == "قواعد\n\nشخصية"
