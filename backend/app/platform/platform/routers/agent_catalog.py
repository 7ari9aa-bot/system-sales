"""Agent catalog — the CODE truth the owner console's agents pages render.

The console stores no agent knowledge of its own: this endpoint projects the
live ``AgentRegistry`` (agent kinds, capabilities) and the ``TOOLS`` spec
registry (tool names, merchant-grade descriptions, risk levels) so the console
can never show a stale copy of what the runtime actually runs. Per-tenant
toggle state (``agent_tools.is_active``) is intentionally NOT here — that is
tenant data the console reads and writes directly; this endpoint is the
platform-wide catalog only.

Gate: the same shared ``x-platform-token`` the impersonation surface uses. An
empty configured token disables the endpoint entirely (404) — the console
degrades, the platform never hands its catalog to an unconfigured deployment.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.agent_catalog import agent_catalog_provider
from app.core.config import get_settings
from app.core.errors import PermissionDeniedError

router = APIRouter(prefix="/platform", tags=["platform"])

logger = logging.getLogger(__name__)


def _require_platform_token(request: Request) -> None:
    """Same shared-secret gate as impersonation; empty token = disabled."""
    settings = get_settings()
    if not settings.impersonation_platform_token:
        raise HTTPException(status_code=404, detail="not found")
    provided = request.headers.get("x-platform-token", "")
    # encode() both sides: hmac.compare_digest raises TypeError on non-ASCII
    # str — a hostile header must be a 403, not a 500.
    if not hmac.compare_digest(provided.encode(), settings.impersonation_platform_token.encode()):
        raise PermissionDeniedError("invalid platform token")


class ToolCatalogEntry(BaseModel):
    name: str
    description: str
    risk_level: str
    is_default: bool


class AgentCatalogEntry(BaseModel):
    kind: str
    name: str
    description: str
    definition_version: int
    default_model: str
    guardrail_profile: str
    capabilities: list[dict]
    tools: list[ToolCatalogEntry]


class AgentCatalogOut(BaseModel):
    agents: list[AgentCatalogEntry]


@router.get(
    "/agent-catalog",
    response_model=AgentCatalogOut,
    dependencies=[Depends(_require_platform_token)],
)
async def get_agent_catalog() -> AgentCatalogOut:
    """Every registered agent kind with its tools, straight from the code.

    The catalog arrives through the core provider registry
    (core/agent_catalog.py) — the same dependency inversion as the spend
    surface. Platform never imports ai here: a module-scope platform → ai
    import grows the cross-module ratchet AND closes an import cycle back
    through ai → notifications → platform models
    (test_module_boundaries catches both).
    """
    provider = agent_catalog_provider()
    if provider is None:
        # ai never registered (its module was not imported) — the console
        # degrades the same way it does without the spend provider.
        raise HTTPException(
            status_code=503, detail="agent catalog is unavailable on this deployment"
        )
    return AgentCatalogOut(**provider())
