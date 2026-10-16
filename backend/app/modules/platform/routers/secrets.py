"""Platform secrets management (§68-69) — credentials registration and rotation."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.platform import schemas
from app.modules.platform.routers._deps import TenantContext, require_permission

router = APIRouter(prefix="/platform", tags=["platform"])


class SecretRefCreate(BaseModel):
    """Body for POST /platform/secrets."""

    provider: str = Field(min_length=1, max_length=63)
    scope: str = Field(default="tenant", max_length=63)
    vault_key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1)
    workspace_id: uuid.UUID | None = None


class SecretRotateRequest(BaseModel):
    """Body for POST /platform/secrets/{provider}/rotate."""

    new_value: str = Field(min_length=1)


@router.post("/secrets", response_model=schemas.SecretReferenceOut, status_code=201)
async def create_secret_reference(
    body: SecretRefCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§68: register a secret reference + store the value via SecretStorePort.

    Gated by settings:write like every other credential surface (flags,
    integrations): registering a secret is a configuration action, not
    something any tenant member may do.
    """
    from app.core.secrets import get_secret_store
    from app.modules.platform.service import SecretService

    # Store the actual value in the secret store first
    store = get_secret_store()
    await store.put(body.vault_key, body.value)

    ref = await SecretService.create_reference(
        ctx.session,
        ctx.tenant_id,
        provider=body.provider,
        scope=body.scope,
        vault_key=body.vault_key,
        workspace_id=body.workspace_id,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(ref.id),
        "provider": ref.provider,
        "scope": ref.scope,
        "vault_key": ref.vault_key,
        "version": ref.version,
        "status": ref.status,
    }


@router.post("/secrets/{provider}/rotate", response_model=schemas.SecretRotatedOut)
async def rotate_secret(
    provider: str,
    body: SecretRotateRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§69: rotate a secret — old version stays for grace period.

    Gated by ``settings:write`` exactly like the sibling ``POST /secrets``
    (registration): rotating a live channel credential is a configuration
    action, not something any tenant member — least of all frontline staff —
    may do. §115 counts a missing API-side check as broken authorization even
    where no screen exposes the call, which is the case here: the frontend has
    no secrets surface at all today, so this dependency is the ONLY thing
    standing between a member role and a live provider credential.
    """
    from app.modules.platform.service import SecretService

    ref = await SecretService.rotate_secret(
        ctx.session,
        ctx.tenant_id,
        provider,
        body.new_value,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(ref.id),
        "provider": ref.provider,
        "version": ref.version,
        "rotated_at": ref.rotated_at.isoformat() if ref.rotated_at else None,
        "status": ref.status,
    }
