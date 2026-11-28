"""Turning a licensed product into an installed one.

Licensing and installation are different questions. A plan says what a business
may use; an installation says what it actually switched on, and how far its setup
got. Until this module ran, every workspace was unconfigured, which is why the
route gates let everyone through.

The rule here is deliberately conservative: install only what the live
subscription entitles, and install it as active because the activity setup just
finished. A workspace that bought nothing gets no rows and stays unconfigured
rather than being handed a product it never paid for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.activity_setup import register_setup_completed_hook
from app.modules.applications.manifests import get_manifest
from app.modules.applications.models import WorkspaceAppInstallation
from app.modules.applications.repository import entitled


async def install_entitled(
    session: AsyncSession, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[str]:
    """Install every application the subscription covers, skipping what exists.

    Idempotent: rows already present are left alone, including one a person
    deliberately deactivated, so finishing setup twice never reopens a product
    somebody closed on purpose.
    """
    licensed = await entitled(session, tenant_id=tenant_id, workspace_id=workspace_id)
    # get_manifest raises on an unknown key, so a typo in billing can never
    # quietly install a product that does not exist.
    wanted = sorted(key for key in licensed if get_manifest(key))
    if not wanted:
        return []

    existing = set(
        (
            await session.execute(
                select(WorkspaceAppInstallation.application_key).where(
                    WorkspaceAppInstallation.workspace_id == workspace_id,
                    WorkspaceAppInstallation.application_key.in_(wanted),
                )
            )
        )
        .scalars()
        .all()
    )
    fresh = [key for key in wanted if key not in existing]
    for key in fresh:
        session.add(
            WorkspaceAppInstallation(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                application_key=key,
                state="active",
                is_active=True,
                installed_at=datetime.now(UTC),
            )
        )
    await session.flush()
    return fresh


async def _install_after_setup(ctx, result: dict) -> None:
    """Hook for core's setup completion: licensed products become installed ones."""
    workspace_id = getattr(ctx, "workspace_id", None)
    if workspace_id is None:
        return
    result["applications_installed"] = await install_entitled(
        ctx.session, tenant_id=ctx.tenant_id, workspace_id=workspace_id
    )


register_setup_completed_hook(_install_after_setup)
