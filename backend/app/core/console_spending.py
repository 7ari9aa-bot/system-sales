"""Console spend-provider registry (dependency inversion, §66 precedent).

The owner console needs each tenant's month-to-date AI spend against its §42
cap, but ``platform -> ai`` at import time closes a module cycle
(ai -> ... -> platform) that the boundaries ratchet rightly refuses. This is
the same shape as the §66 audit-writer move: the CROSS-CUTTING surface lives
in core, parameter-bound, and the owning module REGISTERS its implementation
at import time.

Contract: the provider receives ``(session, tenant_ids)`` and returns a
dict keyed by tenant id — see ``app.modules.ai.spend_read`` for the
reference implementation and its RLS caveat (each per-tenant aggregate must
run under the tenant's own GUC).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

Provider = Callable[[Any, list[uuid.UUID]], dict[uuid.UUID, dict[str, Any]]]

_provider: Provider | None = None


def register_console_spend_provider(provider: Provider) -> None:
    """Register the implementation. Re-registration with the SAME callable is
    idempotent; a different callable must replace it explicitly via
    ``force=True`` — mirroring the tool-registry's fail-closed discipline."""
    global _provider
    if _provider is not None and _provider is not provider:
        raise RuntimeError(
            "console spend provider already registered — pass force=True to replace it"
        )
    _provider = provider


def replace_console_spend_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def console_spend_rows(
    session: Any, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Delegate to the registered provider.

    Returns per-tenant dicts with (at least) Decimal-string money fields —
    ``month_spend``, ``cap``, ``cap_source``, ``on_exceed``,
    ``failed_runs_24h`` — the exact shape the owner console's tenants tab
    renders. A missing provider (the ai module never imported — conceivable
    only in a stripped deployment) yields zero-spend rows rather than a 500:
    the console must still render, honestly labeled.
    """
    if _provider is None:
        return {
            tenant_id: {
                "month_spend": Decimal("0"),
                "cap": Decimal("0"),
                "cap_source": "unavailable",
                "on_exceed": "unavailable",
                "failed_runs_24h": 0,
            }
            for tenant_id in tenant_ids
        }
    return _provider(session, tenant_ids)
