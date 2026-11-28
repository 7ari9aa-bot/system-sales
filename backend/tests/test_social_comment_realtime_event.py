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


def test_the_announcement_carries_ids_only_never_the_comment_text() -> None:
    from app.applications.apparel.modules.conversations.social_comments import comment_changed_payload

    payload = comment_changed_payload(
        platform="facebook",
        post_id="p-1",
        comment_id="c-1",
        parent_comment_id="c-0",
        verb="add",
    )
    assert payload == {
        "platform": "facebook",
        "post_id": "p-1",
        "comment_id": "c-1",
        "parent_comment_id": "c-0",
        "verb": "add",
    }
    assert "body" not in payload and "message" not in payload


def test_a_comment_with_no_post_is_not_announced() -> None:
    """A screen refetches by post, so an announcement without one has nobody to wake."""
    from app.applications.apparel.modules.conversations.social_comments import comment_changed_payload

    assert (
        comment_changed_payload(
            platform="facebook", post_id=None, comment_id="c-1", parent_comment_id=None, verb="add"
        )
        is None
    )


async def test_announce_stages_one_outbox_event_on_the_comment_stream(monkeypatch) -> None:
    from app.applications.apparel.modules.conversations import social_comments as mod

    staged: list[dict] = []

    async def fake_add(session, **kw):
        staged.append(kw)

    monkeypatch.setattr(mod, "add_outbox_event", fake_add)
    tenant, row = uuid.uuid4(), uuid.uuid4()
    sent = await mod.announce_comment_changed(
        None,
        tenant,
        row,
        platform="facebook",
        post_id="p-1",
        comment_id="c-1",
        parent_comment_id=None,
        verb="add",
    )
    assert sent is True
    (event,) = staged
    assert event["aggregate_type"] == "social_comment"  # stream = social_comment.events
    assert event["event_type"] == "social_comment.changed"
    assert event["tenant_id"] == tenant and event["aggregate_id"] == row
    assert event["payload"]["post_id"] == "p-1"


async def test_announce_does_nothing_without_a_post(monkeypatch) -> None:
    from app.applications.apparel.modules.conversations import social_comments as mod

    async def boom(*a, **k):
        raise AssertionError("must not stage an event with no post")

    monkeypatch.setattr(mod, "add_outbox_event", boom)
    sent = await mod.announce_comment_changed(
        None,
        uuid.uuid4(),
        uuid.uuid4(),
        platform="facebook",
        post_id=None,
        comment_id="c-1",
        parent_comment_id=None,
        verb="add",
    )
    assert sent is False
