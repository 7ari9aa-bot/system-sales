"""A pending request may not apply over a value that moved while it waited.

The old flow stored the proposal, the submitter, the scope and the reason — never the
revision the proposal was written against. So a request created while the discount cap
was 10 could be approved after someone raised it to 20, and the approval wrote 10-ish
back over the newer value. Approve and reject also read the row without FOR UPDATE, so
two reviewers could both pass the pending_approval check.
"""

from __future__ import annotations

import inspect
import pathlib

from app.platform.settings import service as service_module
from app.platform.settings.models import CHANGE_REQUEST_STATES
from app.platform.settings.service import SettingsService

SOURCE = inspect.getsource(service_module)


def test_the_request_can_record_being_stale():
    assert "stale" in CHANGE_REQUEST_STATES


def test_creation_pins_the_revision_each_key_stood_at():
    src = inspect.getsource(SettingsService.create_change_request)
    assert "_latest_history_ids" in src
    assert "base_history_ids" in src


def test_approval_refuses_when_the_value_moved():
    src = inspect.getsource(SettingsService.approve_change_request)
    assert "_keys_changed_since" in src
    assert 'request.status = "stale"' in src
    # and it says which keys moved, so the reviewer knows what happened. The decision
    # returns instead of raising (a raise rolled it back), so the message is composed in
    # the router, from the keys the service attached to the returned request.
    assert "stale_keys" in src
    router = pathlib.Path(__file__).resolve().parents[1] / "app/platform/settings/router.py"
    body = router.read_text(encoding="utf-8")
    assert "changed after it was submitted" in body


def test_approve_and_reject_lock_the_row():
    for fn in (SettingsService.approve_change_request, SettingsService.reject_change_request):
        assert "with_for_update()" in inspect.getsource(fn)


def test_a_request_without_a_pinned_base_is_not_refused():
    src = inspect.getsource(SettingsService._keys_changed_since)
    assert "if not base:" in src
    assert "return set()" in src
