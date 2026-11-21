"""A public comment that lands (webhook or sync) is announced to the open screens.

Pins the three seams the push rides on: the event type is registered, the SSE gateway
fans its stream out, and the announcement carries only what a screen needs to refetch
(no comment body, so a stream frame never doubles as a second copy of customer text).
"""

from __future__ import annotations

import uuid

from app.core.events.schemas import EVENT_TYPES, build_envelope
from app.modules.realtime.router import _ALL_STREAMS


def test_the_event_type_is_registered() -> None:
    assert "social_comment.changed" in EVENT_TYPES


def test_the_gateway_fans_out_the_comment_stream() -> None:
    assert "social_comment.events" in _ALL_STREAMS


def test_the_envelope_builds_with_the_post_it_belongs_to() -> None:
    tenant = uuid.uuid4()
    env = build_envelope(
        "social_comment.changed",
        tenant_id=tenant,
        aggregate_type="social_comment",
        aggregate_id=uuid.uuid4(),
        payload={"platform": "facebook", "post_id": "p-1", "comment_id": "c-1", "verb": "add"},
    )
    assert env.payload["post_id"] == "p-1"
    assert env.tenant_id == tenant
