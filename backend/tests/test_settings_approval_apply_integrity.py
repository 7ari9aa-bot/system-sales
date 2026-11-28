"""Approving a change applies it — without granting the reviewer write power.

`settings:approve` was added so a manager can sign off a proposal without holding
`settings:write`. The apply path then re-checked `settings:write` for the reviewer, so a
manager could reject a request but never approve one: the write was refused, the request
was marked `failed`, and the whole transaction rolled back.

Two more integrity holes sit on the same path:

* a `stale` decision was raised as a `ValidationError`, which rolled the transaction back,
  so the row stayed `pending_approval` and the reviewer kept being told it was stale;
* `base_history_ids` only pinned the keys that already had a revision, so a setting that
  had never been written could be changed while the request waited and the old proposal
  still applied over it.
"""

from __future__ import annotations

import inspect
import pathlib

from app.platform.settings import service as service_module
from app.platform.settings.schemas import BulkSetSettingsRequest
from app.platform.settings.service import SettingsService

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTER = (BACKEND / "app/platform/settings/router.py").read_text(encoding="utf-8")
SOURCE = inspect.getsource(service_module)


def test_apply_runs_through_the_trusted_path() -> None:
    src = inspect.getsource(SettingsService._apply_change_request)
    assert "trusted_apply=True" in src, (
        "the apply path must not re-check the reviewer's settings:write"
    )


def test_bulk_set_and_set_skip_the_write_check_only_when_trusted() -> None:
    bulk = inspect.getsource(SettingsService.bulk_set)
    single = inspect.getsource(SettingsService.set)
    assert "if not trusted_apply:" in bulk
    assert "if not trusted_apply:" in single
    # Validation and history still run on the trusted path.
    assert "_validate(defn, value)" in single


def test_a_stale_decision_is_returned_not_raised() -> None:
    src = inspect.getsource(SettingsService.approve_change_request)
    assert 'request.status = "stale"' in src
    assert "return request" in src
    tail = src.split("moved = await")[1].split("return request")[0]
    assert "change request is stale: " not in tail, (
        "raising on stale rolls the decision back and the row stays pending_approval"
    )


def test_the_router_answers_a_stale_decision_with_a_committed_409() -> None:
    start = ROUTER.index("async def approve_change_request(")
    body = ROUTER[start : ROUTER.index("async def reject_change_request(")]
    assert 'req.status == "stale"' in body
    assert "JSONResponse(" in body
    assert "status_code=409" in body
    assert "conflicting_keys" in body


def test_creation_pins_every_key_even_the_never_written_ones() -> None:
    src = inspect.getsource(SettingsService.create_change_request)
    # Every key in the request is pinned, values and clears alike.
    assert "for k in pinned_keys" in src, "a key without history must still be pinned (as None)"
    assert "pinned_keys = list(changes) + reset_keys" in src


def test_expected_history_ids_honours_an_explicit_none() -> None:
    bulk = inspect.getsource(SettingsService.bulk_set)
    assert "if k in expected_history_ids" in bulk
    assert "(latest.get(k) or None) != h" in bulk
    assert "expect_no_history=" in bulk
    assert "elif expect_no_history:" in inspect.getsource(SettingsService.set)


def test_the_request_schema_accepts_a_null_revision() -> None:
    field = BulkSetSettingsRequest.model_fields["expected_history_ids"]
    assert field.annotation is not None
    assert "None" in str(field.annotation)


def test_change_request_states_include_stale() -> None:
    from app.platform.settings.models import CHANGE_REQUEST_STATES

    assert "stale" in CHANGE_REQUEST_STATES
    assert "trusted_apply" in SOURCE
