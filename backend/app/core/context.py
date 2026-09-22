"""Request-scoped observability context (§65/§66).

The request-id and correlation-id contextvars live in ``app.core.errors``
(predating this module — the error contract publishes them); they are
re-exported here so ``app.core.context`` is the single import site for
request lineage. New code should import from here.

- ``actor_kind_contextvar`` — who/what is acting, on §66's vocabulary:
  "human" | "ai" | "automation" | "system" | "integration". Set by the edge
  middleware (human/automation) and the worker runtime (system); AI tool
  paths may set "ai". Read by the audit writer so §66's ``source`` column is
  populated from context, never from a caller argument (an argument could lie
  about which request caused the write).
- ``credentials_audit_contextvar`` — per-request/event set of integration
  ids whose credential decryption was already audited, so §68 access auditing
  emits ONE audit row per integration per request instead of one per decrypt.
"""

from __future__ import annotations

from contextvars import ContextVar

from app.core.errors import correlation_id_contextvar, request_id_contextvar

actor_kind_contextvar: ContextVar[str | None] = ContextVar("actor_kind", default=None)

# Ids (as strings) of integrations whose credentials were decrypted — and
# audited — in the current request/event scope. A fresh set is installed per
# HTTP request (app.main middleware) and per bus event (workers/base.py).
credentials_audit_contextvar: ContextVar[set[str] | None] = ContextVar(
    "credentials_audit", default=None
)

__all__ = [
    "actor_kind_contextvar",
    "correlation_id_contextvar",
    "credentials_audit_contextvar",
    "request_id_contextvar",
]
