"""SocialService on a real database: the platform is faked, our rules are not."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError, ExternalProviderError, NotFoundError, ValidationError
from app.modules.conversations import social_service as ss
from app.modules.conversations.models import SocialComment, SocialPost
from app.modules.conversations.social_service import SocialService

CREDS = {"api_key": "t", "account_id": "ig1"}


def _ago(hours: int) -> str:
    """A provider timestamp relative to now, in the format Meta sends.

    These were written out as fixed dates, so every one of them eventually fell outside
    Meta's 7-day private-reply window and the provider-rejection test started hitting our
    own window rule instead of the provider. A fake that ages is a fake that lies.
    """
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+0000")


class FakeInstagram:
    """Records every call and can be told to fail, like a provider that rejects."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail = False
        self.media = [
            {
                "id": "p1",
                "caption": "new shoes",
                "media_type": "IMAGE",
                "media_product_type": "FEED",
                "permalink": "https://ig/p1",
                "timestamp": _ago(30),
                "like_count": 4,
                "comments_count": 2,
            },
            {
                "id": "p2",
                "caption": "reel",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "timestamp": _ago(54),
            },
        ]
        self.comments = [
            {
                "id": "c1",
                "text": "price?",
                "username": "sara",
                "timestamp": _ago(20),
                "from": {"id": "u1", "username": "sara"},
                "replies": {
                    "data": [
                        {
                            "id": "c2",
                            "text": "dm me",
                            "username": "omar",
                            "timestamp": _ago(19),
                            "from": {"id": "u2"},
                        }
                    ]
                },
            },
            {
                "id": "c3",
                "text": "spam",
                "username": "bot",
                "hidden": True,
                "timestamp": _ago(18),
            },
        ]

    def _go(self, *call):
        self.calls.append(call)
        if self.fail:
            raise ExternalProviderError("provider said no")

    async def list_media(self, creds, limit=25, after=None):
        self._go("list_media")
        return {"items": self.media, "next": None}

    async def list_comments(self, creds, media_id, **kw):
        self._go("list_comments", media_id)
        return {"items": self.comments, "next": None}

    async def reply_to_comment(self, creds, comment_id, text):
        self._go("reply", comment_id, text)
        return "new-reply-1"

    async def set_comment_hidden(self, creds, comment_id, hidden):
        self._go("hide", comment_id, hidden)

    async def delete_comment(self, creds, comment_id):
        self._go("delete", comment_id)

    async def send_private_reply(self, creds, comment_id, text):
        self._go("private", comment_id, text)
        return "dm-1"

    async def set_comments_enabled(self, creds, media_id, enabled):
        self._go("toggle", media_id, enabled)


@pytest.fixture
def ig(monkeypatch) -> FakeInstagram:
    fake = FakeInstagram()
    monkeypatch.setattr(ss, "instagram_adapter", fake)
    return fake


async def _comment(db, tenant_id, cid="c1", **kw) -> SocialComment:
    row = SocialComment(
        tenant_id=tenant_id,
        platform="instagram",
        comment_id=cid,
        post_id="p1",
        body="hello",
        commented_at=kw.pop("commented_at", datetime.now(UTC)),
        status="visible",
        **kw,
    )
    db.add(row)
    await db.flush()
    return row


async def test_sync_posts_upserts_and_marks_reels(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    assert await SocialService.sync_posts(db, t, CREDS) == 2
    assert await SocialService.sync_posts(db, t, CREDS) == 2  # idempotent
    posts = {p.post_id: p for p in await SocialService.list_posts(db, t)}
    assert set(posts) == {"p1", "p2"} and posts["p1"].caption == "new shoes"
    assert posts["p2"].media_type == "REELS" and posts["p1"].comments_count == 2
    assert [p.post_id for p in await SocialService.list_posts(db, t)] == [
        "p1",
        "p2",
    ]  # newest first


async def test_sync_comments_threads_replies_and_keeps_hidden(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    assert await SocialService.sync_comments(db, t, CREDS, "p1") == 3
    rows = {c.comment_id: c for c in await SocialService.list_comments(db, t, "p1")}
    assert rows["c2"].parent_comment_id == "c1" and rows["c1"].username == "sara"
    assert rows["c3"].status == "hidden"
    assert [
        c.comment_id for c in await SocialService.list_comments(db, t, "p1", include_hidden=False)
    ] == ["c1", "c2"]


async def test_a_sync_never_undoes_a_moderation_decision(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    await SocialService.sync_comments(db, t, CREDS, "p1")
    await SocialService.set_hidden(db, t, CREDS, "c1", True)
    await SocialService.sync_comments(db, t, CREDS, "p1")  # the platform page still says visible
    assert (await SocialService.get_comment(db, t, "c1")).status == "hidden"
    await SocialService.delete(db, t, CREDS, "c2")
    await SocialService.sync_comments(db, t, CREDS, "p1")
    with pytest.raises(NotFoundError):
        await SocialService.get_comment(db, t, "c2")  # a stale page cannot resurrect it


async def test_public_reply_goes_to_the_thread_root_and_is_recorded(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    await SocialService.sync_comments(db, t, CREDS, "p1")
    reply = await SocialService.reply_publicly(
        db, t, CREDS, "c2", "  thanks  "
    )  # c2 is a reply to c1
    assert ig.calls[-1] == ("reply", "c1", "thanks")  # Instagram threads are one level deep
    assert reply.is_page_reply and reply.parent_comment_id == "c1" and reply.body == "thanks"
    assert (await SocialService.get_comment(db, t, "c1")).replied_at is not None


async def test_reply_is_validated_before_any_provider_call(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    await SocialService.sync_comments(db, t, CREDS, "p1")
    for bad in ("", "   ", "x" * 2201):
        with pytest.raises(ValidationError):
            await SocialService.reply_publicly(db, t, CREDS, "c1", bad)
    with pytest.raises(ConflictError):  # c3 is hidden
        await SocialService.reply_publicly(db, t, CREDS, "c3", "hi")
    with pytest.raises(NotFoundError):
        await SocialService.reply_publicly(db, t, CREDS, "nope", "hi")
    assert ig.calls == [("list_comments", "p1")]  # nothing reached the provider


async def test_a_provider_rejection_leaves_our_rows_untouched(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    await SocialService.sync_comments(db, t, CREDS, "p1")
    ig.fail = True
    for call in (
        SocialService.reply_publicly(db, t, CREDS, "c1", "hi"),
        SocialService.set_hidden(db, t, CREDS, "c1", True),
        SocialService.delete(db, t, CREDS, "c1"),
        SocialService.send_private_reply(db, t, CREDS, "c1", "hi"),
    ):
        with pytest.raises(ExternalProviderError):
            await call
    c1 = await SocialService.get_comment(db, t, "c1")
    assert (c1.status, c1.replied_at, c1.private_replied_at) == ("visible", None, None)
    n = len(
        (await db.execute(select(SocialComment).where(SocialComment.is_page_reply.is_(True))))
        .scalars()
        .all()
    )
    assert n == 0


async def test_hide_then_unhide_records_who_and_when(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    c = await _comment(db, t)
    await SocialService.set_hidden(db, t, CREDS, "c1", True, user_id=tenant_ctx.user.id)
    assert (c.status, c.moderated_by) == ("hidden", tenant_ctx.user.id) and c.hidden_at is not None
    await SocialService.set_hidden(db, t, CREDS, "c1", False)
    assert c.status == "visible" and c.hidden_at is None


async def test_private_reply_is_once_per_comment(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    c = await _comment(db, t)
    assert await SocialService.send_private_reply(db, t, CREDS, "c1", "price is 50") == "dm-1"
    assert c.private_replied_at is not None
    with pytest.raises(ConflictError):
        await SocialService.send_private_reply(db, t, CREDS, "c1", "again")
    assert [x for x in ig.calls if x[0] == "private"] == [("private", "c1", "price is 50")]


async def test_private_reply_window_is_exactly_seven_days(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    posted = datetime.now(UTC)
    await _comment(db, t, "in", commented_at=posted)
    await _comment(db, t, "late", commented_at=posted)
    await SocialService.send_private_reply(db, t, CREDS, "in", "ok", now=posted + timedelta(days=7))
    with pytest.raises(ConflictError):
        await SocialService.send_private_reply(
            db, t, CREDS, "late", "too late", now=posted + timedelta(days=7, seconds=1)
        )


async def test_no_private_reply_to_our_own_reply(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    await _comment(db, t, "mine", is_page_reply=True)
    with pytest.raises(ValidationError):
        await SocialService.send_private_reply(db, t, CREDS, "mine", "hi")


async def test_toggle_comments_updates_the_post(db, tenant_ctx, ig) -> None:
    t = tenant_ctx.tenant_id
    await SocialService.sync_posts(db, t, CREDS)
    await SocialService.set_comments_enabled(db, t, CREDS, "p1", False)
    post = (await db.execute(select(SocialPost).where(SocialPost.post_id == "p1"))).scalar_one()
    assert post.comments_enabled is False
    with pytest.raises(NotFoundError):
        await SocialService.set_comments_enabled(db, t, CREDS, "missing", True)
