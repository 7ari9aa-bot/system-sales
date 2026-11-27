"""GPT-Live delegates, we answer — once, and out loud.

The protocol here is not guessed: `delegation: {type: client}` is accepted at
session.start on the real gateway, and a context frame carrying a delegation_id
the server never issued comes back as "Unknown client or Decision delegation".
So these tests pin the two things that matter operationally: every reply carries
a real delegation id, and a redelivered delegation never buys a second answer.
"""

from __future__ import annotations

import pytest

from app.modules.voice.application.client_delegation import (
    FAILURE_NOTE,
    ClientDelegationService,
    parse_delegation,
)
from app.modules.voice.runtime.gpt_live import GptLiveConfig, GptLiveProtocolError, GptLiveProvider

SESSION = "live_test_1"


class _Provider:
    """Records what would have been sent, in order."""

    def __init__(self) -> None:
        self.frames: list[tuple[str, str, str]] = []

    async def append_thinking(self, session_id, *, delegation_id, content, event_id=None):
        self.frames.append(("thinking", delegation_id, content))
        return "e"

    async def append_commentary(self, session_id, *, delegation_id, content, event_id=None):
        self.frames.append(("commentary", delegation_id, content))
        return "e"


def _created(delegation_id="item_1", target="client"):
    return {
        "type": "session.delegation.created",
        "offset_ms": 4200,
        "delegation": {"id": delegation_id, "target": target},
    }


def _runner(answer="المبيعات النهاردة 12 ألف", *, boom=False):
    calls: list[tuple[str, str]] = []

    async def run(transcript: str, idempotency_key: str) -> str:
        calls.append((transcript, idempotency_key))
        if boom:
            raise RuntimeError("the backend is down")
        return answer

    run.calls = calls  # type: ignore[attr-defined]
    return run


async def test_a_delegation_is_acknowledged_then_answered_from_the_same_brain():
    provider = _Provider()
    runner = _runner()
    service = ClientDelegationService(provider, runner)

    outcome = await service.on_event(SESSION, _created(), transcript="كام مبيعات النهاردة؟")

    assert outcome == "answered"
    # First an empty thinking frame (the protocol's "work has started"), then the
    # answer as commentary — both on the SAME delegation id the gateway issued.
    assert provider.frames == [
        ("thinking", "item_1", ""),
        ("commentary", "item_1", "المبيعات النهاردة 12 ألف"),
    ]
    # The turn ran once, with the caller's words and an idempotency key derived
    # from the delegation, so a retry lands on the same turn instead of a new one.
    assert runner.calls == [("كام مبيعات النهاردة؟", "delegation:item_1")]


async def test_a_redelivered_delegation_is_not_run_twice():
    provider = _Provider()
    runner = _runner()
    service = ClientDelegationService(provider, runner)

    first = await service.on_event(SESSION, _created(), transcript="كام مبيعات النهاردة؟")
    second = await service.on_event(SESSION, _created(), transcript="كام مبيعات النهاردة؟")

    assert (first, second) == ("answered", "duplicate")
    assert len(runner.calls) == 1
    assert [f[0] for f in provider.frames] == ["thinking", "commentary"]


async def test_a_failed_turn_is_told_to_the_model_instead_of_vanishing():
    provider = _Provider()
    service = ClientDelegationService(provider, _runner(boom=True))

    outcome = await service.on_event(SESSION, _created(), transcript="كام مبيعات النهاردة؟")

    assert outcome == "failed"
    # Acknowledged, then a note the model can say — and never a commentary frame
    # that would claim an answer we do not have.
    assert provider.frames == [("thinking", "item_1", ""), ("thinking", "item_1", FAILURE_NOTE)]


async def test_an_empty_answer_is_not_spoken():
    provider = _Provider()
    service = ClientDelegationService(provider, _runner(answer="   "))

    outcome = await service.on_event(SESSION, _created(), transcript="كام مبيعات النهاردة؟")

    assert outcome == "failed"
    assert ("commentary", "item_1", "   ") not in provider.frames


async def test_other_events_and_malformed_delegations_are_left_alone():
    provider = _Provider()
    runner = _runner()
    service = ClientDelegationService(provider, runner)

    assert await service.on_event(SESSION, {"type": "session.started"}, transcript="x") == "ignored"
    assert (
        await service.on_event(
            SESSION, {"type": "session.delegation.created", "delegation": {}}, transcript="x"
        )
        == "ignored"
    )
    assert provider.frames == []
    assert runner.calls == []


def test_parse_delegation_reads_the_id_and_target():
    request = parse_delegation(_created(delegation_id="item_9tA", target="orders"))

    assert request is not None
    assert (request.delegation_id, request.target, request.offset_ms) == (
        "item_9tA",
        "orders",
        4200,
    )


async def test_the_adapter_refuses_to_answer_a_delegation_it_was_never_given():
    """The gateway's own refusal, caught before the frame is sent."""
    provider = GptLiveProvider(GptLiveConfig(api_key="k", voice="marin"), transport_factory=None)

    with pytest.raises(GptLiveProtocolError):
        await provider.append_commentary("live_x", delegation_id="  ", content="تم")
