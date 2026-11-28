"""Publishing to Instagram sends its pictures in one JSON body, so it needs more than 1 MiB."""

from __future__ import annotations

import pytest

from app.core.middleware import MAX_BODY_BYTES, MAX_SOCIAL_POST_BYTES, BodySizeLimitMiddleware

MB = 1024 * 1024


async def _app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _status(method: str, path: str, size: int) -> int:
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"x" * size, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"content-length", str(size).encode())],
    }
    await BodySizeLimitMiddleware(_app)(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_the_limit_holds_the_largest_post_the_publish_screen_allows():
    # 10 pictures of 8 MB, each sent as base64 (4/3 of its size) inside one JSON body.
    from app.applications.apparel.modules.conversations.gateway.instagram import InstagramAdapter
    from app.applications.apparel.modules.conversations.social_service import MAX_PICTURE_BYTES

    largest = InstagramAdapter.CAROUSEL_MAX * (-(-MAX_PICTURE_BYTES // 3) * 4 + 20) + 200
    assert largest <= MAX_SOCIAL_POST_BYTES


@pytest.mark.parametrize("size_mb", [2, 12, 60, 107])
async def test_a_real_photo_post_is_not_refused_as_too_large(size_mb):
    # A phone photo is 2-6 MB and base64 adds a third; under 1 MiB every one of these was a 413.
    assert await _status("POST", "/api/v1/social/posts", size_mb * MB) == 200


async def test_a_post_past_the_publishing_limit_is_still_refused():
    assert await _status("POST", "/api/v1/social/posts", MAX_SOCIAL_POST_BYTES + 1) == 413


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/social/comments/c1/reply"),  # same prefix, not the publishing route
        ("POST", "/api/v1/social/posts/p1/comments-enabled"),
        ("GET", "/api/v1/social/posts"),  # only the POST that carries pictures
        ("POST", "/api/v1/conversations"),
    ],
)
async def test_nothing_else_gets_the_larger_body(method, path):
    assert await _status(method, path, MAX_BODY_BYTES + 1) == 413
