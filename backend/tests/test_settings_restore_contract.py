"""A snapshot restore is tenant-wide, and it proposes what it cannot write.

Two contract bugs lived here. The history scan was not filtered to tenant scope, so a
restore also rewrote branch and register overrides the owner never saw on the restore
screen. And APPROVAL_REQUIRED keys were counted as "pending_approval" while nothing was
ever created, so a restore reported work that no reviewer would ever see.
"""

from __future__ import annotations

import inspect
import pathlib

from app.modules.settings.service import SettingsService

SOURCE = pathlib.Path(inspect.getfile(SettingsService)).read_text(encoding="utf-8")
START = SOURCE.index("async def restore_to_snapshot")
REST = SOURCE[START + 10 :]
BODY = SOURCE[START : START + 10 + REST.index("\n    async def ")]


def test_the_history_scan_is_tenant_only() -> None:
    assert "TenantSettingHistory.scope == Scope.TENANT.value" in BODY
    assert "TenantSettingHistory.scope_id.is_(None)" in BODY


def test_the_override_scan_is_tenant_only() -> None:
    assert "TenantSetting.scope == Scope.TENANT.value" in BODY
    assert "TenantSetting.scope_id.is_(None)" in BODY


def test_the_result_states_the_scope_it_restored() -> None:
    assert '"scope": Scope.TENANT.value' in BODY


def test_approval_required_keys_open_a_real_change_request() -> None:
    assert "await self.create_change_request(" in BODY
    # Both the value case and the clear case propose rather than skip.
    # Three proposals now: the restored value, the clear of a key the snapshot did not
    # have, and the clear of a key added after the snapshot.
    assert BODY.count("await self.create_change_request(") == 3
    assert "pending_approval += 1" in BODY

    # Each counter is bumped in the same block as the request it describes.
    lines = BODY.splitlines()
    for i, line in enumerate(lines):
        if "pending_approval += 1" in line:
            window = "\n".join(lines[max(0, i - 14) : i + 1])
            assert "create_change_request" in window, "counted as pending with no request"
