"""What a tool-call audit row is allowed to claim as its idempotency key (§15-16).

The key is what makes `uq_tool_calls_tenant_idempotency` dedupe a side effect.
Its whole purpose is "this conversation's message already produced this order",
so it must be claimed by calls that EXECUTED and by nothing else — otherwise the
row that records an approval PARK owns the key the RESUME needs, the resume's
audit insert loses its own unique-constraint race, and the code returns the
park's `awaiting_approval` outcome for an action that actually ran.

Pure, so the invariant is checkable without a database. The end-to-end version
of that failure is `test_approval_gate.py::test_a_resumed_action_audits_the_execution`.
"""

from __future__ import annotations

import uuid

from app.modules.ai.runtime import compute_tool_idempotency_key

CONVERSATION = uuid.uuid4()
MESSAGE = uuid.uuid4()
RUN = uuid.uuid4()
OTHER_RUN = uuid.uuid4()


def _key(**overrides):
    args = {
        "risk_level": "HIGH",
        "conversation_id": CONVERSATION,
        "inbound_message_id": MESSAGE,
        "run_id": RUN,
        "tool_call_id": "tc_1",
        "tool_name": "create_order",
        "arguments": {"items": [{"variant_id": "v1", "quantity": 2}]},
        "status": "ok",
    }
    args.update(overrides)
    return compute_tool_idempotency_key(**args)


def test_a_park_claims_no_key():
    """The row that says "waiting for a human" performed no side effect."""
    assert _key(status="awaiting_approval") is None
    assert _key(status="denied") is None
    # And an executed call does, so the rule is about the status, not the tool.
    assert _key(status="ok") is not None


def test_the_parks_key_would_have_collided_with_the_resumes():
    """Spelled out so the regression cannot be re-introduced quietly.

    Same conversation, same inbound message, same tool, same arguments — which is
    exactly what a resume presents, because hooks._do_auto_reply answers the
    conversation's LAST inbound message. Only the run id differs, and the semantic
    key deliberately ignores it: so ANY rule that lets a non-executed row claim a
    key makes the park and the resume claim the same one.
    """
    assert _key(run_id=OTHER_RUN) == _key(run_id=RUN)
    assert _key(run_id=OTHER_RUN) == _key(run_id=RUN, status="ok")


def test_arguments_are_part_of_the_key():
    """Approving quantity 2 must not dedupe a later quantity 3."""
    assert _key(arguments={"items": [{"quantity": 2}]}) != _key(
        arguments={"items": [{"quantity": 3}]}
    )


def test_argument_order_does_not_change_the_key():
    """`sort_keys=True` is the whole point: the same order typed differently is
    the same side effect, and deduping it is the desired behaviour."""
    assert _key(arguments={"a": 1, "b": 2}) == _key(arguments={"b": 2, "a": 1})


def test_the_inbound_message_is_the_discriminator():
    """P0-6: a NEW message with identical items is a NEW order, not a retry."""
    assert _key(inbound_message_id=MESSAGE) != _key(inbound_message_id=uuid.uuid4())


def test_reads_key_on_the_provider_call_not_the_tool_name():
    """Two `check_stock` calls in one turn are usually about two variants.

    Keying them by tool name would make the second return the first's cached
    answer, and the model would report stock for the wrong product with a
    straight face — so LOW tools stay keyed per provider tool_call id.
    """
    first = _key(risk_level="LOW", tool_name="check_stock")
    same_tool_other_call = _key(risk_level="LOW", tool_name="check_stock", tool_call_id="tc_2")
    other_run = _key(risk_level="LOW", tool_name="check_stock", run_id=OTHER_RUN)
    assert first.startswith(f"{RUN}:")
    assert first != same_tool_other_call
    assert first != other_run


def test_a_side_effect_without_a_conversation_falls_back_to_the_run():
    """A conversation-less caller has no semantic scope to dedupe against, so the
    run key is the only honest one."""
    key = _key(conversation_id=None)
    assert key == f"{RUN}:tc_1"


def test_medium_risk_is_a_side_effect_too():
    assert _key(risk_level="MEDIUM") == _key(risk_level="HIGH")
