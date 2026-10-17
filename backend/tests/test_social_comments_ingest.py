"""Social comments layer — parse, durable ingest, webhook wiring.

Pure pins: the shared Meta comment parser handles BOTH envelope families
(page "feed" with item=comment, Instagram field "comments"), skips anything
that is not a comment, and never raises on a malformed delivery.
DB-backed pins: idempotent ingest keyed by (tenant, platform, comment_id),
the platform's own verbs (edited/remove), the remove-before-add tombstone,
and the webhook sync block persisting comments without fanning them out.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.conversations.gateway.base import parse_meta_comment_changes
from app.modules.conversations.gateway.facebook import facebook_adapter
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.gateway.messenger import messenger_adapter
from app.modules.conversations.models import SocialComment

FB_ADD = {
    "object": "page",
    "entry": [
        {
            "id": "page-1",
            "time": 1700000100,
            "changes": [
                {
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "verb": "add",
                        "comment_id": "c-100",
                        "post_id": "p-200",
                        "parent_id": "c-99",
                        "from": {"id": "user-1", "name": "محمد"},
                        "message": "المنتج ده جميل",
                        "created_time": 1700000000,
                        "permalink_url": "https://fb.test/c-100",
                        "like_count": 3,
                    },
                }
            ],
        }
    ],
}

IG_ADD = {
    "object": "instagram",
    "entry": [
        {
            "id": "ig-1",
            "time": 1700000100,
            "changes": [
                {
                    "field": "comments",
                    "value": {
                        "id": "ig-c-1",
                        "text": "متوفر مقاس M؟",
                        "from": {"id": "ig-user-1", "username": "shopper_1"},
                        "media": {"id": "media-9", "media_product_type": "FEED"},
                        "parent_id": "ig-c-0",
                        "timestamp": "2026-10-17T10:00:00+0000",
                        "permalink": "https://ig.test/p/ig-c-1",
                    },
                }
            ],
        }
    ],
}


def test_page_feed_comment_parses():
    (comment,) = parse_meta_comment_changes(FB_ADD)
    assert comment.platform_comment_id == "c-100"
    assert comment.post_id == "p-200"
    assert comment.parent_comment_id == "c-99"
    assert comment.author_ref == "user-1"
    assert comment.author_name == "محمد"
    assert comment.body == "المنتج ده جميل"
    assert comment.verb == "add"
    assert comment.like_count == 3
    assert comment.permalink == "https://fb.test/c-100"
    assert comment.commented_at is not None and comment.commented_at.tzinfo is not None


def test_instagram_comment_parses():
    (comment,) = parse_meta_comment_changes(IG_ADD)
    assert comment.platform_comment_id == "ig-c-1"
    assert comment.post_id == "media-9"
    assert comment.author_name == "shopper_1"
    assert comment.body == "متوفر مقاس M؟"
    assert comment.parent_comment_id == "ig-c-0"


def test_non_comment_changes_are_skipped():
    payload = {
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {"field": "feed", "value": {"item": "like", "verb": "add"}},
                    {"field": "messages", "value": {"messaging": {}}},
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "comment_id": "c-real",
                            "message": "حقيقي",
                        },
                    },
                ],
            }
        ]
    }
    (comment,) = parse_meta_comment_changes(payload)
    assert comment.platform_comment_id == "c-real"  # only the real comment survived


def test_malformed_comment_never_raises():
    payload = {
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {"field": "feed", "value": {"item": "comment", "verb": "add"}},
                    {"field": "feed", "value": None},
                    {"field": "comments", "value": {"text": "no id here"}},
                ],
            }
        ]
    }
    assert parse_meta_comment_changes(payload) == []
    assert parse_meta_comment_changes({}) == []
    assert parse_meta_comment_changes({"entry": []}) == []


def test_remove_forces_body_none_and_edited_keeps_verb():
    edited = {
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "edited",
                            "comment_id": "c-100",
                            "message": "المنتج ده جميل جداً",
                        },
                    }
                ],
            }
        ]
    }
    (comment,) = parse_meta_comment_changes(edited)
    assert comment.verb == "edited"
    removed = {
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "remove",
                            "comment_id": "c-100",
                            "message": "should not survive",
                        },
                    }
                ],
            }
        ]
    }
    (comment,) = parse_meta_comment_changes(removed)
    assert comment.verb == "remove"
    assert comment.body is None


def test_meta_adapters_expose_the_comment_parser():
    # Messenger → Facebook inheritance; Instagram's own adapter.
    for adapter in (messenger_adapter, facebook_adapter, instagram_adapter):
        parsed = adapter.parse_comments(FB_ADD)
        assert len(parsed) == 1, adapter.name


async def test_ingest_is_idempotent_and_edits_update(db, tenant_ctx) -> None:
    from app.modules.conversations.social_comments import SocialCommentService

    tenant_id = tenant_ctx.tenant_id
    first = parse_meta_comment_changes(FB_ADD)[0]
    row_id = await SocialCommentService.ingest(
        db, tenant_id, platform="facebook", comment=first
    )
    again = await SocialCommentService.ingest(
        db, tenant_id, platform="facebook", comment=first
    )
    assert row_id == again
    rows = (
        (
            await db.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.comment_id == "c-100",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].body == "المنتج ده جميل"

    edited = parse_meta_comment_changes(
        {
            "entry": [
                {
                    "id": "page-1",
                    "changes": [
                        {
                            "field": "feed",
                            "value": {
                                "item": "comment",
                                "verb": "edited",
                                "comment_id": "c-100",
                                "message": "تمام",
                                "like_count": 9,
                            },
                        }
                    ],
                }
            ]
        }
    )[0]
    await SocialCommentService.ingest(db, tenant_id, platform="facebook", comment=edited)
    (row,) = (
        (
            await db.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.comment_id == "c-100",
                )
            )
        )
        .scalars()
        .all()
    )
    assert row.body == "تمام"
    assert row.like_count == 9


async def test_remove_marks_removed_and_a_late_add_cannot_resurrect(db, tenant_ctx) -> None:
    from app.modules.conversations.social_comments import SocialCommentService

    tenant_id = tenant_ctx.tenant_id
    parser_input = lambda verb: {  # noqa: E731
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": verb,
                            "comment_id": "c-gone",
                            "message": "سيبها",
                        },
                    }
                ],
            }
        ]
    }
    # remove BEFORE add: the tombstone is written so the key is honest.
    removed = parse_meta_comment_changes(parser_input("remove"))[0]
    await SocialCommentService.ingest(db, tenant_id, platform="facebook", comment=removed)
    (row,) = (
        (
            await db.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.comment_id == "c-gone",
                )
            )
        )
        .scalars()
        .all()
    )
    assert row.status == "removed"

    # A redelivered add must not resurrect a removed comment as visible.
    added = parse_meta_comment_changes(parser_input("add"))[0]
    await SocialCommentService.ingest(db, tenant_id, platform="facebook", comment=added)
    (row,) = (
        (
            await db.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.comment_id == "c-gone",
                )
            )
        )
        .scalars()
        .all()
    )
    assert row.status == "removed"


async def test_process_webhook_event_persists_comments_without_fanout(
    db, tenant_ctx
) -> None:
    """The webhook sync block stores the comment and marks the ingress row
    processed — comments never become messages, so no AI run can trigger."""
    from app.modules.conversations.gateway.ingest import IngestService
    from app.modules.platform.models import WebhookEvent

    tenant_id = tenant_ctx.tenant_id

    class _StubAdapter:
        channel = "facebook"

        def parse_inbound(self, payload):
            return []

        def parse_status_updates(self, payload):
            return []

        def parse_comments(self, payload):
            return parse_meta_comment_changes(payload)

    event = WebhookEvent(
        provider="facebook",
        external_event_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        signature_valid=True,
        payload=FB_ADD,
        processing_status="pending",
    )
    db.add(event)
    await db.flush()

    accepted = await IngestService.process_webhook_event(
        db,
        adapter=_StubAdapter(),
        channel="facebook",
        tenant_id=tenant_id,
        event_id=event.id,
        payload=FB_ADD,
    )
    assert accepted == 1
    (row,) = (
        (
            await db.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.comment_id == "c-100",
                )
            )
        )
        .scalars()
        .all()
    )
    assert row.body == "المنتج ده جميل"
    assert row.commented_at.date() == datetime(2023, 11, 14, tzinfo=UTC).date()
    (event_row,) = (
        (
            await db.execute(
                select(WebhookEvent).where(WebhookEvent.id == event.id)
            )
        )
        .scalars()
        .all()
    )
    assert event_row.processing_status == "processed"


@pytest.mark.usefixtures("db")
async def test_same_comment_on_two_platforms_is_two_rows(db, tenant_ctx) -> None:
    """The dedupe key is (tenant, platform, comment_id): a comment that also
    surfaces through a second integration is not silently dropped."""
    from app.modules.conversations.social_comments import SocialCommentService

    tenant_id = tenant_ctx.tenant_id
    comment = parse_meta_comment_changes(IG_ADD)[0]
    await SocialCommentService.ingest(db, tenant_id, platform="instagram", comment=comment)
    await SocialCommentService.ingest(db, tenant_id, platform="facebook", comment=comment)
    rows = (
        (
            await db.execute(
                select(SocialComment).where(
                    SocialComment.tenant_id == tenant_id,
                    SocialComment.comment_id == "ig-c-1",
                )
            )
        )
        .scalars()
        .all()
    )
    assert {row.platform for row in rows} == {"instagram", "facebook"}
