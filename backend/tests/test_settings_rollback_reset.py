"""Rolling back a reset restores the value the reset removed.

The old code took ``action == "reset"`` to mean "delete the override again": it removed
the current row, wrote a second reset history row, and returned before the
APPROVAL_REQUIRED gate. So the merchant asking to undo a reset got another reset, and a
setting that needs approval could be cleared with no change request at all.
"""

from __future__ import annotations

import inspect

from app.modules.settings import service as service_module
from app.modules.settings.service import SettingsService, rollback_restore_value


def test_rolling_back_a_reset_restores_the_value_before_it():
    """A reset removed 10; undoing it puts 10 back, not another reset."""
    assert rollback_restore_value("reset", {"v": 10}, None) == 10


def test_rolling_back_a_set_restores_what_that_revision_wrote():
    assert rollback_restore_value("set", {"v": 5}, {"v": 10}) == 10


def test_a_reset_that_removed_nothing_restores_nothing():
    """No previous override means there is no value to put back."""
    assert rollback_restore_value("reset", None, None) is None


def test_rollback_no_longer_deletes_the_override_for_a_reset():
    """The reset branch must not delete a row: that is the bug being fixed."""
    source = inspect.getsource(SettingsService.rollback)
    assert "delete(TenantSetting)" not in source
    assert "rollback_restore_value(" in source


def test_approval_gate_comes_before_any_write_on_the_reset_path():
    """A reset rollback reaches create_change_request before it reaches set()."""
    source = inspect.getsource(SettingsService.rollback)
    approval_at = source.index("create_change_request")
    write_at = source.index("await self.set(")
    assert approval_at < write_at


def test_the_helper_is_used_by_the_service():
    assert service_module.rollback_restore_value is rollback_restore_value
