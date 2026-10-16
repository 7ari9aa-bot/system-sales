"""AI agent management routes — kinds, CRUD, prompt editing, publishing."""

import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.core.idempotency import IfMatch, apply_etag, apply_versioned_update
from app.modules.ai.models import Agent
from app.modules.ai.routers._deps import (
    SettingsCtx,
    SettingsReadCtx,
    TenantCtxDep,
)
from app.modules.ai.schemas import (
    AgentCreateRequest,
    AgentDetailOut,
    AgentKindOut,
    AgentOut,
    AgentPublishRequest,
    AgentUpdateRequest,
    AgentVersionOut,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/agent-kinds")
async def list_agent_kinds(ctx: TenantCtxDep) -> list[AgentKindOut]:
    """List all registered agent kinds and their definitions.

    This is the platform's extensibility surface: a new agent kind added
    to the registry appears here automatically."""
    from app.modules.ai.core.registry import AgentRegistry
    from app.modules.ai.schemas import AgentCapabilityOut

    return [
        AgentKindOut(
            kind=defn.kind,
            name=defn.name,
            description=defn.description,
            definition_version=defn.definition_version,
            default_model=defn.default_model,
            capabilities=[
                AgentCapabilityOut(name=c.name, description=c.description, required=c.required)
                for c in defn.capabilities
            ],
            default_tools=defn.default_tools,
            allowed_tools=defn.allowed_tools,
            task_types=defn.task_types,
            guardrail_profile=defn.guardrail_profile,
            provisioning_policy=defn.provisioning_policy,
        )
        for defn in AgentRegistry.get_all()
    ]


@router.get("/agents")
async def list_agents(ctx: TenantCtxDep) -> list[AgentOut]:
    rows = (
        await ctx.session.execute(
            select(Agent).where(Agent.tenant_id == ctx.tenant_id).order_by(Agent.created_at.asc())
        )
    ).scalars()
    return [AgentOut.model_validate(agent) for agent in rows]


@router.post("/agents", status_code=201)
async def create_agent(ctx: SettingsCtx, body: AgentCreateRequest) -> AgentOut:
    from app.core.errors import ConflictError, ValidationError
    from app.modules.ai.core.registry import AgentRegistry
    from app.modules.ai.models import AgentTool

    defn = AgentRegistry.get_or_none(body.kind)
    if defn is None:
        raise ValidationError(
            f"Unknown agent kind '{body.kind}'. Registered kinds: {AgentRegistry.kinds()}"
        )

    singleton = (defn.provisioning_policy or {}).get("singleton_per_tenant", True)
    if singleton:
        existing = (
            await ctx.session.execute(
                select(Agent).where(
                    Agent.tenant_id == ctx.tenant_id,
                    Agent.kind == body.kind,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"Agent of kind '{body.kind}' already exists for this tenant")

    model = body.model or defn.default_model
    base = defn.system_prompt_template
    if (defn.provisioning_policy or {}).get("is_canonical"):
        if body.system_prompt and body.system_prompt.strip():
            custom = body.system_prompt.strip()
            if base and base not in custom:
                system_prompt = f"{base}\n\n[Tenant Instructions]\n{custom}"
            else:
                system_prompt = custom
        else:
            system_prompt = base
    else:
        system_prompt = body.system_prompt or base

    agent = Agent(
        tenant_id=ctx.tenant_id,
        kind=body.kind,
        name=body.name,
        model=model,
        system_prompt=system_prompt,
        description=body.description or defn.description,
    )
    ctx.session.add(agent)
    await ctx.session.flush()

    for tool_name in defn.default_tools:
        if not AgentRegistry.is_tool_authorized(body.kind, tool_name):
            raise ValidationError(
                f"Tool '{tool_name}' is not authorized for agent kind '{body.kind}'"
            )
        ctx.session.add(
            AgentTool(
                tenant_id=ctx.tenant_id,
                agent_id=agent.id,
                name=tool_name,
                policy={},
            )
        )
    if defn.default_tools:
        await ctx.session.flush()

    return AgentOut.model_validate(agent)


@router.get("/agents/{agent_id}/prompt", response_model=AgentDetailOut)
async def get_agent_detail(
    agent_id: uuid.UUID,
    ctx: SettingsReadCtx,
    response: Response,
) -> AgentDetailOut:
    """Fetch one agent including prompt — tenant-isolated by the WHERE clause and RLS."""
    agent = (
        await ctx.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"agent {agent_id} not found")
    apply_etag(response, agent.version)
    return AgentDetailOut.model_validate(agent)


@router.patch("/agents/{agent_id}", response_model=AgentDetailOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdateRequest,
    ctx: SettingsCtx,
    response: Response,
    if_match: IfMatch = None,
) -> AgentDetailOut:
    """Tenant edits their own agent settings / prompt with optimistic concurrency (ADR-060)."""
    agent = (
        await ctx.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"agent {agent_id} not found")

    fields = body.model_dump(exclude_unset=True)
    if fields:
        if "system_prompt" in fields and fields["system_prompt"] is not None:
            from app.modules.ai.core.registry import AgentRegistry

            defn = AgentRegistry.get_or_none(agent.kind)
            if defn and (defn.provisioning_policy or {}).get("is_canonical"):
                base = defn.system_prompt_template
                custom = fields["system_prompt"].strip()
                if base and base not in custom:
                    fields["system_prompt"] = f"{base}\n\n[Tenant Instructions]\n{custom}"
                else:
                    fields["system_prompt"] = custom
        await apply_versioned_update(ctx.session, agent, if_match, fields)

    apply_etag(response, agent.version)
    return AgentDetailOut.model_validate(agent)


@router.post("/agents/{agent_id}/publish", status_code=201, response_model=AgentVersionOut)
async def publish_agent_version(
    agent_id: uuid.UUID,
    ctx: SettingsCtx,
    body: AgentPublishRequest | None = None,
) -> AgentVersionOut:
    """Snapshot the agent row into an immutable published version.

    Idempotent for identical configuration: republishing unchanged settings
    returns the existing snapshot rather than minting a no-op version.
    """
    from app.modules.ai.versions import AIAgentVersionService

    policy = (body.tool_policy if body is not None else None) or None
    version = await AIAgentVersionService.publish(
        ctx.session,
        ctx.tenant_id,
        agent_id,
        published_by=ctx.user_id,
        tool_policy=policy,
    )
    return AgentVersionOut.model_validate(version)
