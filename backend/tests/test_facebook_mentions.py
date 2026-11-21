"""@mention in a Page's reply (Pages API: Comments and @mentions).

Meta tags a person when the comment text carries `@[PSID]` and the author of that comment or post is
that person (or a Page). The PSID must come from a comment already on the Page, never typed by the
owner, so the client builds the tag itself from ids it was given and refuses anything that is not a
plain numeric id.
"""

import httpx
import pytest

from app.modules.conversations.gateway import facebook_pages as fp

CREDS = {"api_key": "tok", "account_id": "111"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _form(req: httpx.Request) -> dict:
    from urllib.parse import parse_qs

    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


def test_mention_tag_is_meta_syntax_for_one_or_many():
    assert fp.mention_tag(["123"]) == "@[123]"
    assert fp.mention_tag(["123", "456"]) == "@[123,456]"


@pytest.mark.parametrize("bad", ["", "abc", "12 3", "12]3", "@[1]", "1;2"])
def test_a_psid_that_is_not_a_plain_number_is_refused(bad):
    with pytest.raises(ValueError, match="mention"):
        fp.mention_tag([bad])


def test_nobody_to_mention_is_an_error_not_an_empty_tag():
    with pytest.raises(ValueError, match="mention"):
        fp.mention_tag([])


def test_the_same_person_is_tagged_once():
    assert fp.mention_tag(["7", "7", "8"]) == "@[7,8]"


@pytest.mark.asyncio
async def test_a_reply_with_a_mention_puts_the_tag_in_the_message_to_the_comment():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, _form(req)))
        return httpx.Response(200, json={"id": "c2"})

    async with _client(handler) as c:
        out = await fp.facebook_pages.comment(CREDS, "c1", "thanks!", mention=["123"], _client=c)
    assert out == "c2"
    assert seen[0][1].endswith("/c1/comments")
    assert seen[0][2]["message"] == "@[123] thanks!"


@pytest.mark.asyncio
async def test_a_reply_without_a_mention_is_sent_exactly_as_before():
    seen = []

    def handler(req):
        seen.append(_form(req))
        return httpx.Response(200, json={"id": "c2"})

    async with _client(handler) as c:
        await fp.facebook_pages.comment(CREDS, "c1", "thanks!", _client=c)
    assert seen == [{"message": "thanks!"}]


@pytest.mark.asyncio
async def test_a_bad_mention_never_leaves_our_server():
    def handler(req):
        raise AssertionError("no request may be sent")

    async with _client(handler) as c:
        with pytest.raises(ValueError, match="mention"):
            await fp.facebook_pages.comment(CREDS, "c1", "hi", mention=["x]y"], _client=c)


# ---- who may be tagged: only people who wrote on this Page's thread ----
from types import SimpleNamespace  # noqa: E402

from app.core.errors import ValidationError  # noqa: E402
from app.modules.conversations.facebook_service import FacebookService  # noqa: E402


def _c(ref, *, page=False):
    return SimpleNamespace(author_ref=ref, is_page_reply=page)


def test_only_people_who_commented_on_the_thread_can_be_tagged():
    thread = [_c("10"), _c("20"), _c(None), _c("99", page=True)]
    assert FacebookService.resolve_mentions(thread, ["10", "20"]) == ["10", "20"]


def test_a_stranger_or_the_page_itself_cannot_be_tagged():
    thread = [_c("10"), _c("99", page=True)]
    with pytest.raises(ValidationError, match="commented"):
        FacebookService.resolve_mentions(thread, ["55"])
    with pytest.raises(ValidationError, match="commented"):
        FacebookService.resolve_mentions(thread, ["99"])


def test_no_mention_asked_means_nobody_is_resolved():
    assert FacebookService.resolve_mentions([_c("10")], None) == []
    assert FacebookService.resolve_mentions([_c("10")], []) == []


def test_meta_accepts_a_handful_of_tags_not_a_crowd():
    thread = [_c(str(i)) for i in range(1, 12)]
    with pytest.raises(ValidationError, match="at most"):
        FacebookService.resolve_mentions(thread, [str(i) for i in range(1, 12)])
