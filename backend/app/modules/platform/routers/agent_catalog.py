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

from app.core.config import get_settings
from app.core.errors import PermissionDeniedError
from app.modules.ai.core.registry import AgentRegistry, discover_agents
from app.modules.ai.tools import TOOLS

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
    """Every registered agent kind with its tools, straight from the code."""
    discover_agents()
    agents: list[AgentCatalogEntry] = []
    for definition in AgentRegistry.get_all():
        tools = []
        for tool_name in definition.allowed_tools:
            spec = TOOLS.get(tool_name)
            if spec is None:
                # validate_registry() refuses an unknown allowed_tool at boot,
                # so this is unreachable in a healthy process — skip loudly
                # in the log rather than inventing a fake description.
                logger.warning(
                    "agent-catalog: allowed tool %r of kind %r has no registered spec",
                    tool_name,
                    definition.kind,
                )
                continue
            tools.append(
                ToolCatalogEntry(
                    name=spec.name,
                    description=spec.description,
                    risk_level=spec.risk_level,
                    is_default=tool_name in definition.default_tools,
                )
            )
        agents.append(
            AgentCatalogEntry(
                kind=definition.kind,
                name=definition.name,
                description=definition.description,
                definition_version=definition.definition_version,
                default_model=definition.default_model,
                guardrail_profile=definition.guardrail_profile,
                capabilities=[cap.model_dump() for cap in definition.capabilities],
                tools=tools,
            )
        )
    return AgentCatalogOut(agents=agents)
