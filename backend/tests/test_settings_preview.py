"""The dry run: the whole diff, checked, with nothing written.

The settings screen previews a save before the owner commits. That preview must be the
SERVER's answer — the same validation the write would run — not a client-side diff that
cannot know which key is out of range, forbidden at this scope, or waiting for approval.
"""

from __future__ import annotations

import uuid

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration
from app.core.db import bind_tenant
from app.modules.identity.services.auth import AuthService
from app.modules.settings.registry import Scope
from app.modules.settings.service import SettingsService


async def _tenant(db):
    _, tenant = await AuthService.register(
        db,
        tenant_name="Preview Co",
        tenant_slug=f"preview-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="preview-pass-1",
        full_name="Preview Owner",
    )
    await bind_tenant(db, tenant.id)
    return tenant


@pytest.mark.asyncio
async def test_preview_reports_the_change_and_writes_nothing(db) -> None:
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)
    before = await svc.value("pos.return_max_days")

    result = await svc.preview({"pos.return_max_days": 7}, scope=Scope.TENANT)

    entry = result["keys"][0]
    assert entry["action"] == "change"
    assert entry["current"] == before
    assert entry["proposed"] == 7
    assert entry["error"] is None
    assert result["summary"]["changes"] == 1
    # The whole point: a preview is not a write.
    assert await svc.value("pos.return_max_days") == before


@pytest.mark.asyncio
async def test_one_bad_key_does_not_hide_the_others(db) -> None:
    """bulk_set raises on the first bad key; a preview must show every key at once."""
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)

    result = await svc.preview(
        {"pos.return_max_days": 7, "business.type": "not-a-business-type"},
        scope=Scope.TENANT,
    )

    by_key = {e["key"]: e for e in result["keys"]}
    assert by_key["pos.return_max_days"]["action"] == "change"
    assert by_key["business.type"]["action"] == "invalid"
    assert by_key["business.type"]["error"]
    assert result["summary"] == {"changes": 1, "unchanged": 0, "needs_approval": 0, "invalid": 1}


@pytest.mark.asyncio
async def test_an_approval_required_key_is_flagged_not_applied(db) -> None:
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)
    before = await svc.value("security.audit_retention_days")

    result = await svc.preview({"security.audit_retention_days": 30}, scope=Scope.TENANT)

    entry = result["keys"][0]
    assert entry["needs_approval"] is True
    assert entry["action"] == "change"
    assert result["summary"]["needs_approval"] == 1
    assert await svc.value("security.audit_retention_days") == before


@pytest.mark.asyncio
async def test_proposing_the_current_value_is_unchanged(db) -> None:
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)
    current = await svc.value("pos.return_max_days")

    result = await svc.preview({"pos.return_max_days": current}, scope=Scope.TENANT)

    assert result["keys"][0]["action"] == "unchanged"
    assert result["summary"]["changes"] == 0


@pytest.mark.asyncio
async def test_an_unknown_key_is_reported_not_raised(db) -> None:
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)

    result = await svc.preview({"not.a.setting": 1}, scope=Scope.TENANT)

    assert result["keys"][0]["action"] == "invalid"
    assert "unknown setting" in result["keys"][0]["error"]
