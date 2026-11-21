"""A post with more comments than one Meta page holds must not lose the rest.

`list_comments` asks Meta for 50 at a time and says where the next page starts. The sync used to
read the first page only, so on a busy post every comment after the 50th, and every reply past a
comment's first 25, never reached the Page's feed and could never be answered.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.modules.conversations import facebook_service as fs
from app.modules.conversations.facebook_service import FacebookService
from app.modules.conversations.models import SocialComment

CREDS = {"api_key": "t", "account_id": "111"}


def _c(i, **kw):
    return {
        "id": f"c{i}",
        "message": f"m{i}",
        "created_time": "2026-11-21T01:00:00+0000",
        "from": {"id": str(1000 + i), "name": f"P{i}"},
        **kw,
    }


class FakePages:
    """Meta's comment pages: `pages` is a list of (items, next_cursor); replies pages by parent."""

    def __init__(self, pages, reply_pages=None):
        self.pages = pages
        self.reply_pages = reply_pages or {}
        self.calls: list[tuple] = []

    async def list_comments(self, credentials, object_id, *, limit=50, after=None, _client=None):
        self.calls.append((object_id, after))
        if object_id in self.reply_pages:
            pages = self.reply_pages[object_id]
        else:
            pages = self.pages
        index = 0 if after is None else int(after)
        items, nxt = pages[index]
        return {"items": items, "next": nxt}


@pytest.fixture
def pages(monkeypatch):
    def install(fake):
        monkeypatch.setattr(fs, "facebook_pages", fake)
        return fake

    return install


async def _count(db, tenant_id):
    return (
        await db.execute(
            select(func.count())
            .select_from(SocialComment)
            .where(SocialComment.tenant_id == tenant_id)
        )
    ).scalar_one()


async def test_every_page_of_comments_is_read_not_just_the_first(db, tenant_ctx, pages) -> None:
    fake = pages(FakePages([([_c(1), _c(2)], "1"), ([_c(3), _c(4)], "2"), ([_c(5)], None)]))
    n = await FacebookService.sync_comments(db, tenant_ctx.tenant_id, CREDS, "111_9")
    assert n == 5
    assert await _count(db, tenant_ctx.tenant_id) == 5
    assert [after for _post, after in fake.calls] == [None, "1", "2"]


async def test_a_post_with_a_single_page_is_read_once(db, tenant_ctx, pages) -> None:
    fake = pages(FakePages([([_c(1)], None)]))
    assert await FacebookService.sync_comments(db, tenant_ctx.tenant_id, CREDS, "111_9") == 1
    assert len(fake.calls) == 1


async def test_a_comment_with_more_replies_than_fit_inline_gets_them_all(
    db, tenant_ctx, pages
) -> None:
    top = _c(1, comments={"data": [_c(11)], "paging": {"next": "https://graph/next"}})
    pages(
        FakePages(
            [([top], None)],
            reply_pages={"c1": [([_c(11), _c(12)], "1"), ([_c(13)], None)]},
        )
    )
    await FacebookService.sync_comments(db, tenant_ctx.tenant_id, CREDS, "111_9")
    ids = {
        c.comment_id
        for c in (
            await db.execute(
                select(SocialComment).where(SocialComment.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    }
    assert ids == {"c1", "c11", "c12", "c13"}
    rows = (
        await db.execute(select(SocialComment).where(SocialComment.comment_id.in_(["c12", "c13"])))
    ).scalars()
    assert {r.parent_comment_id for r in rows} == {"c1"}


async def test_a_runaway_cursor_cannot_loop_forever(db, tenant_ctx, pages) -> None:
    # Meta answering with the same cursor for ever must stop at the cap, not hang the request.
    class Loop(FakePages):
        async def list_comments(
            self, credentials, object_id, *, limit=50, after=None, _client=None
        ):
            self.calls.append((object_id, after))
            return {"items": [_c(len(self.calls))], "next": "again"}

    fake = pages(Loop([]))
    n = await FacebookService.sync_comments(db, tenant_ctx.tenant_id, CREDS, "111_9")
    assert n == fs.MAX_COMMENT_PAGES
    assert len(fake.calls) == fs.MAX_COMMENT_PAGES
