"""Every settings path that returns a stored value goes through one mask.

``/effective``, ``/overrides`` and ``/history`` masked SENSITIVE values from the start, but
``/change-requests``, ``/preview``, the approve/reject responses, ``/rollback`` and the preset
dry run returned the stored value raw — so a caller without ``settings:read_sensitive`` could
read a secret from a second door. These tests pin the single helper those paths now share.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.platform.settings.registry import REGISTRY, Sensitivity, get_definition
from app.platform.settings.router import (
    MASKED_VALUE,
    _change_request_to_out,
    _mask_if_sensitive,
    _mask_mapping,
)

SENSITIVE_KEY = next(
    key for key, defn in REGISTRY.items() if defn.sensitivity is Sensitivity.SENSITIVE
)
PLAIN_KEY = next(
    key for key, defn in REGISTRY.items() if defn.sensitivity is not Sensitivity.SENSITIVE
)


def test_mask_mapping_hides_sensitive_keys_and_keeps_the_rest():
    """A map of key -> value masks only the keys the caller may not read."""
    values = {SENSITIVE_KEY: "s3cret", PLAIN_KEY: 15}

    masked = _mask_mapping(values, can_read_sensitive=False)

    assert masked == {SENSITIVE_KEY: MASKED_VALUE, PLAIN_KEY: 15}
    # The caller's own dict is untouched: masking is a view, not a mutation.
    assert values[SENSITIVE_KEY] == "s3cret"


def test_mask_mapping_is_a_noop_with_the_permission():
    values = {SENSITIVE_KEY: "s3cret"}
    assert _mask_mapping(values, can_read_sensitive=True) == values


def test_mask_mapping_passes_through_empty_and_unknown_keys():
    assert _mask_mapping(None, can_read_sensitive=False) is None
    assert _mask_mapping({}, can_read_sensitive=False) == {}
    assert _mask_mapping({"not.a.key": 1}, can_read_sensitive=False) == {"not.a.key": 1}


def test_a_sensitive_false_is_masked_not_shown_as_false():
    """The UI bug behind this work: a masked BOOL must not look like a real ``false``."""
    defn = get_definition(SENSITIVE_KEY)
    assert _mask_if_sensitive(defn, False, False) == MASKED_VALUE
    assert _mask_if_sensitive(defn, True, False) == MASKED_VALUE
    assert _mask_if_sensitive(defn, False, True) is False


def test_change_request_output_masks_changes_and_applied_changes():
    """Both maps on a change request are masked for a reviewer without the permission."""
    now = dt.datetime.now(dt.UTC)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        changes={SENSITIVE_KEY: "s3cret", PLAIN_KEY: 15},
        applied_changes={SENSITIVE_KEY: "s3cret"},
        status="pending_approval",
        scope="tenant",
        scope_id=None,
        submitted_by=uuid.uuid4(),
        reviewed_by=None,
        reason="test",
        review_note=None,
        created_at=now,
        updated_at=now,
    )

    masked = _change_request_to_out(row, can_read_sensitive=False)
    assert masked.changes == {SENSITIVE_KEY: MASKED_VALUE, PLAIN_KEY: 15}
    assert masked.applied_changes == {SENSITIVE_KEY: MASKED_VALUE}

    plain = _change_request_to_out(row, can_read_sensitive=True)
    assert plain.changes[SENSITIVE_KEY] == "s3cret"
    assert plain.applied_changes[SENSITIVE_KEY] == "s3cret"


def test_an_allowed_caller_gets_the_real_value_back():
    """Regression: the mask used to fall off the end and answer ``None`` for everyone.

    That made /effective, /overrides and /history return null for the owner — the one
    caller who is allowed to read everything.
    """
    sensitive = get_definition(SENSITIVE_KEY)
    plain = get_definition(PLAIN_KEY)

    assert _mask_if_sensitive(sensitive, "s3cret", True) == "s3cret"
    assert _mask_if_sensitive(plain, 15, True) == 15
    # A plain setting is never masked, even without the permission.
    assert _mask_if_sensitive(plain, 15, False) == 15
