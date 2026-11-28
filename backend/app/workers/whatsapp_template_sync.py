"""Keep every WhatsApp template's review state in step with Meta.

Meta reviews a template after we submit it (minutes to a day) and may pause one later when its
quality drops, so our copy goes stale unless somebody asks again. This sweep asks, for each
store that has a template living on Meta, at most once per run.

Only stores with such a template are visited, and a store whose WhatsApp is no longer connected
is skipped without a call. One store failing never stops the others.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.applications.apparel.modules.conversations.models import MessageTemplate
from app.applications.apparel.modules.conversations.templates import TemplateService
from app.modules.platform.models import Integration

logger = logging.getLogger(__name__)

#: Statuses that can still change on Meta's side. A draft was never sent there, and an archived
#: or rejected template is final until the owner edits and resubmits it.
WATCHED_STATUSES = ("submitted", "approved", "paused")


async def _tenants_with_meta_templates() -> list[uuid.UUID]:
    """The stores that have at least one template Meta may still change."""
    from app.modules.identity.models import Tenant

    async with SessionLocal() as session:
        # Tenant is read first (RLS-free list), then each store is entered on its own binding.
        tenant_ids = (
            (await session.execute(select(Tenant.id).where(Tenant.is_active))).scalars().all()
        )
    found: list[uuid.UUID] = []
    for tenant_id in tenant_ids:
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                has_one = (
                    await session.execute(
                        select(MessageTemplate.id)
                        .where(
                            MessageTemplate.tenant_id == tenant_id,
                            MessageTemplate.provider == "whatsapp",
                            MessageTemplate.category.is_not(None),
                            MessageTemplate.category != "",
                            MessageTemplate.status.in_(WATCHED_STATUSES),
                        )
                        .limit(1)
                    )
                ).first()
        if has_one is not None:
            found.append(tenant_id)
    return found


async def sync_one_tenant(tenant_id: uuid.UUID, *, _client=None) -> dict | None:
    """Sync one store; None when its WhatsApp is not connected (nothing was asked of Meta)."""
    async with SessionLocal() as session:
        async with session.begin():
            await bind_tenant(session, tenant_id)
            integration = (
                await session.execute(
                    select(Integration).where(
                        Integration.tenant_id == tenant_id,
                        Integration.provider == "whatsapp",
                        Integration.kind == "channel",
                        Integration.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if integration is None:
                return None
            from app.modules.platform.services.channel_access import channel_credentials_config

            credentials = await channel_credentials_config(session, tenant_id, "whatsapp")
            if not credentials or not credentials.get("access_token"):
                return None
            return await TemplateService.sync_from_meta(
                session, tenant_id, credentials=credentials, _client=_client
            )


async def sweep_template_status() -> int:
    """Cross-tenant sweep. Returns how many templates changed state."""
    changed = 0
    for tenant_id in await _tenants_with_meta_templates():
        try:
            result = await sync_one_tenant(tenant_id)
        except Exception:  # noqa: BLE001 - one store's Meta error must not stop the rest
            logger.exception("whatsapp_template_sync.failed tenant=%s", tenant_id)
            continue
        if result:
            changed += len(result.get("changed") or [])
    return changed
