"""Agent-catalog provider registry — the platform's dependency inversion for
reading agent/tool CODE truth without importing the ai module.

Same contract as ``core/console_spending.py``: the owning module (ai) registers
a provider at import time; platform surfaces call the registry and get plain
data. A missing provider is an honest unavailable, never a crash — the owner
console degrades the same way it does when the spend provider is absent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

AgentCatalogProvider = Callable[[], dict[str, Any]]

_provider: AgentCatalogProvider | None = None


def register_agent_catalog_provider(provider: AgentCatalogProvider) -> None:
    """Wire the ai module's catalog builder (called at ai import time)."""
    global _provider
    _provider = provider


def agent_catalog_provider() -> AgentCatalogProvider | None:
    """The registered provider, or None when ai was never imported."""
    return _provider
