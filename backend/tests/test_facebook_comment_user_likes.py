"""Whether the Page itself has liked a comment: Meta's `user_likes` field on the Comment node.

Graph API v27 Comment: `user_likes` (bool) "Whether the viewer has liked this comment". With a Page
token the viewer is the Page. Without reading it, the Like button always started un-pressed after a
reload, even for a comment the Page had liked.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.modules.conversations.facebook_service import _page_liked
from app.modules.conversations.gateway.facebook_pages import COMMENT_FIELDS
from app.modules.conversations.models import SocialComment
from app.modules.conversations.routers.social import _comment_out


def test_the_comment_request_asks_meta_for_user_likes() -> None:
    assert "user_likes" in COMMENT_FIELDS.split(",")


def test_user_likes_true_is_read_as_liked() -> None:
    assert _page_liked({"user_likes": True}) is True


def test_a_missing_or_false_user_likes_is_not_liked() -> None:
    # Meta leaves the field out when it is false for some tokens.
    assert _page_liked({}) is False
    assert _page_liked({"user_likes": False}) is False
    assert _page_liked({"user_likes": None}) is False


def test_a_malformed_user_likes_is_not_liked_not_a_crash() -> None:
    assert _page_liked({"user_likes": "yes"}) is False
    assert _page_liked({"user_likes": 1}) is False
    assert _page_liked(None) is False


def test_the_model_has_a_defaulted_page_liked_column() -> None:
    col = SocialComment.__table__.c.page_liked
    assert col.nullable is False
    assert str(col.server_default.arg) == "false"


def test_the_comment_output_carries_page_liked() -> None:
    row = SimpleNamespace(
        comment_id="1_2",
        post_id="1",
        parent_comment_id=None,
        username="a",
        author_name="a",
        body="hi",
        like_count=2,
        commented_at=datetime(2026, 11, 21, tzinfo=UTC),
        status="visible",
        is_page_reply=True,
        replied_at=None,
        private_replied_at=None,
        page_liked=True,
    )
    assert _comment_out(row)["page_liked"] is True
