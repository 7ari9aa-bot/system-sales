"""The Page's event feed: what the webhook records, and the read mark that is now shared.

The notifications screen used to be rebuilt from the post list with its read mark in
`localStorage`. These tests pin the three things that fixes: every feed event the report named
becomes a row (including a mention, which carries ids only), a retried delivery does not become a
second notification, and marking read is one tenant-wide write instead of a per-browser key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.applications.apparel.modules.conversations.page_activity_service import (
    KINDS,
    PageActivityService,
    summary_for,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _change(item: str, **value) -> dict:
    return {"field": "feed", "value": {"item": item, "post_id": "P1", **value}}


async def test_a_new_post_becomes_a_notification(db, tenant_ctx):
    written = await PageActivityService.record_changes(
        db, tenant_ctx.tenant_id, "facebook", [_change("post", message="عرض جديد", verb="add")]
    )
    assert written == {"written": 1, "duplicates": 0, "ignored": 0}

    rows = await PageActivityService.list_activity(db, tenant_ctx.tenant_id, channel="facebook")
    assert [r.kind for r in rows] == ["post"]
    assert rows[0].object_id == "P1"
    assert rows[0].read_at is None


async def test_every_event_the_report_named_is_recorded(db, tenant_ctx):
    """A mention, an edit, a delete, a reaction and a comment — not just "a post happened"."""
    changes = [
        {"field": "mention", "value": {"post_id": "P1", "created_time": 1_700_000_001}},
        _change("post", edited=True, created_time=1_700_000_002),
        _change("post", verb="remove", created_time=1_700_000_003),
        _change("reaction", verb="add", created_time=1_700_000_004),
        {
            "field": "feed",
            "value": {
                "item": "comment",
                "comment_id": "C1",
                "post_id": "P1",
                "created_time": 1_700_000_005,
            },
        },
    ]

    await PageActivityService.record_changes(db, tenant_ctx.tenant_id, "facebook", changes)

    rows = await PageActivityService.list_activity(db, tenant_ctx.tenant_id, channel="facebook")
    assert sorted(r.kind for r in rows) == sorted(
        ["mention", "post_edit", "post_delete", "reaction", "comment"]
    )
    for row in rows:
        assert row.kind in KINDS
        assert row.summary == summary_for(row.kind)


async def test_a_retried_delivery_is_one_notification(db, tenant_ctx):
    """Meta retries a delivery for up to seven days; the merchant must not see it twice."""
    change = _change("post", message="عرض", created_time=1_700_000_010)

    first = await PageActivityService.record_changes(db, tenant_ctx.tenant_id, "facebook", [change])
    second = await PageActivityService.record_changes(
        db, tenant_ctx.tenant_id, "facebook", [change]
    )

    assert first["written"] == 1 and second["written"] == 0
    assert second["duplicates"] == 1
    rows = await PageActivityService.list_activity(db, tenant_ctx.tenant_id, channel="facebook")
    assert len(rows) == 1


async def test_two_reactions_a_minute_apart_are_two_events(db, tenant_ctx):
    """The timestamp is part of the identity: same object, different minute, different event."""
    await PageActivityService.record_changes(
        db,
        tenant_ctx.tenant_id,
        "facebook",
        [
            _change("reaction", created_time=1_700_000_020),
            _change("reaction", created_time=1_700_000_080),
        ],
    )
    rows = await PageActivityService.list_activity(db, tenant_ctx.tenant_id, channel="facebook")
    assert len(rows) == 2


async def test_an_event_about_a_post_we_do_not_hold_is_still_recorded(db, tenant_ctx):
    """The Page may have been connected after that post was written; the news is still real."""
    await PageActivityService.record_changes(
        db, tenant_ctx.tenant_id, "facebook", [_change("post", post_id="OLD-1", message="قديم")]
    )
    rows = await PageActivityService.list_activity(db, tenant_ctx.tenant_id, channel="facebook")
    assert [r.object_id for r in rows] == ["OLD-1"]


async def test_a_change_with_no_object_is_not_invented(db, tenant_ctx):
    outcome = await PageActivityService.record_changes(
        db, tenant_ctx.tenant_id, "facebook", [{"field": "feed", "value": {"item": "post"}}]
    )
    assert outcome == {"written": 0, "duplicates": 0, "ignored": 1}


async def test_marking_read_is_one_tenant_wide_write(db, tenant_ctx):
    await PageActivityService.record_changes(
        db,
        tenant_ctx.tenant_id,
        "facebook",
        [
            _change("post", created_time=1_700_000_030),
            _change("reaction", created_time=1_700_000_031),
        ],
    )

    marked = await PageActivityService.mark_read(db, tenant_ctx.tenant_id, channel="facebook")
    assert marked == 2

    rows = await PageActivityService.list_activity(db, tenant_ctx.tenant_id, channel="facebook")
    assert all(r.read_at is not None for r in rows)
    # A second call changes nothing: the mark is a fact, not a counter.
    assert await PageActivityService.mark_read(db, tenant_ctx.tenant_id, channel="facebook") == 0


async def test_marking_read_up_to_a_time_leaves_the_newer_ones_unread(db, tenant_ctx):
    await PageActivityService.record_changes(
        db, tenant_ctx.tenant_id, "facebook", [_change("post", created_time=1_700_000_040)]
    )
    cutoff = datetime.fromtimestamp(1_700_000_040, tz=UTC) - timedelta(seconds=1)

    assert (
        await PageActivityService.mark_read(
            db, tenant_ctx.tenant_id, channel="facebook", up_to=cutoff
        )
        == 0
    )
    unread = await PageActivityService.list_activity(
        db, tenant_ctx.tenant_id, channel="facebook", only_unread=True
    )
    assert len(unread) == 1


async def test_activity_is_tenant_and_channel_scoped(db, tenant_ctx):
    """Two tenants, one Page id each: neither sees the other's feed."""
    from app.applications.apparel.modules.conversations.models import PageActivity

    other_tenant = tenant_ctx.tenant_id
    await PageActivityService.record(
        db,
        other_tenant,
        channel="instagram",
        kind="live_comment",
        object_id="C9",
        occurred_at=NOW,
    )

    facebook = await PageActivityService.list_activity(db, other_tenant, channel="facebook")
    instagram = await PageActivityService.list_activity(db, other_tenant, channel="instagram")
    assert facebook == [] and [r.object_id for r in instagram] == ["C9"]
    assert all(isinstance(r, PageActivity) for r in instagram)
