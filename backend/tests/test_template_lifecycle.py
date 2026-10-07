"""Spec §31 - message template lifecycle.

The state machine is the gate that makes the 24h-window enforcement usable: a
template is only sendable once it is APPROVED, and these tests pin the rules
that stop an unvetted (or silently edited) template reaching a customer.

Pure unit tests over the transition table plus the input validation - no
database needed.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.modules.conversations.templates import (
    ALLOWED_TRANSITIONS,
    EDITABLE_STATUSES,
    KNOWN_PROVIDERS,
    TemplateInput,
    TemplateService,
    _validate,
)

GOOD = TemplateInput(
    name="order_update",
    body_text="طلبك رقم {{1}} خرج للتوصيل",
    language="ar",
    provider="whatsapp",
    variables=("1",),
)


# --- validation -------------------------------------------------------------


def test_a_well_formed_template_validates() -> None:
    _validate(GOOD)


def test_provider_must_be_a_channel_that_supports_templates() -> None:
    """Sending a 'whatsapp' template over a channel with no template flow is a
    category error, so it is refused at creation rather than at send time."""
    assert "whatsapp" in KNOWN_PROVIDERS
    assert "telegram" not in KNOWN_PROVIDERS
    assert "webchat" not in KNOWN_PROVIDERS
    with pytest.raises(ValidationError):
        _validate(TemplateInput(name="t", body_text="b", provider="telegram"))


@pytest.mark.parametrize(
    "bad",
    [
        TemplateInput(name="   ", body_text="b"),
        TemplateInput(name="t", body_text="   "),
        TemplateInput(name="t", body_text="b", variables=("bad name",)),
        TemplateInput(name="t", body_text="b", variables=("",)),
    ],
)
def test_invalid_inputs_are_refused(bad: TemplateInput) -> None:
    with pytest.raises(ValidationError):
        _validate(bad)


def test_variable_count_is_bounded() -> None:
    too_many = TemplateInput(name="t", body_text="b", variables=tuple(f"v{i}" for i in range(50)))
    with pytest.raises(ValidationError):
        _validate(too_many)


# --- the state machine ------------------------------------------------------


def test_only_draft_and_rejected_are_editable() -> None:
    """An approved template was already vetted by the provider; editing it in
    place would change what the customer receives."""
    assert EDITABLE_STATUSES == {"draft", "rejected"}
    for status in ("submitted", "approved", "paused", "archived"):
        assert status not in EDITABLE_STATUSES


def test_the_happy_path_is_draft_submit_approve() -> None:
    assert "submitted" in ALLOWED_TRANSITIONS["draft"]
    assert "approved" in ALLOWED_TRANSITIONS["submitted"]
    assert "paused" in ALLOWED_TRANSITIONS["approved"]


def test_a_rejected_template_can_be_fixed_and_resubmitted() -> None:
    assert "submitted" in ALLOWED_TRANSITIONS["rejected"]


def test_a_paused_template_can_be_resumed_without_reapproval() -> None:
    """Pausing is reversible: the provider already vetted the content."""
    assert "approved" in ALLOWED_TRANSITIONS["paused"]


def test_archived_is_terminal() -> None:
    assert ALLOWED_TRANSITIONS["archived"] == frozenset()


def test_every_state_can_be_archived_except_archived() -> None:
    for status, targets in ALLOWED_TRANSITIONS.items():
        if status == "archived":
            continue
        assert "archived" in targets, status


def test_no_state_can_jump_straight_to_approved() -> None:
    """Approval must always pass through `submitted`, so there is a review
    record for every approved template."""
    for status, targets in ALLOWED_TRANSITIONS.items():
        if status == "submitted":
            continue
        assert "approved" not in targets or status == "paused", status


def test_transitions_never_reference_unknown_states() -> None:
    known = set(ALLOWED_TRANSITIONS)
    for status, targets in ALLOWED_TRANSITIONS.items():
        assert targets <= known, (status, targets - known)


def test_rejection_requires_a_reason() -> None:
    """A rejection with no reason is unactionable for the author."""

    class _NoDb:
        pass

    # reject() validates the reason before it touches the session, so a missing
    # reason must fail on its own rather than as an AttributeError.
    import asyncio

    with pytest.raises(ValidationError):
        asyncio.run(TemplateService.reject(_NoDb(), None, None, reason="   ", reviewer="staff"))
