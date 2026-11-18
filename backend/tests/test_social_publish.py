"""Publishing from the inbox: what is refused first, cleaned up, and recorded last."""

from __future__ import annotations

import base64
import uuid

import pytest

from app.core.errors import ConflictError, ExternalProviderError, ValidationError
from app.modules.conversations import social_service as ss
from app.modules.conversations.routers.social import _decode_picture
from app.modules.conversations.social_service import SocialService

CREDS = {"api_key": "t", "account_id": "ig1"}
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64
TENANT = uuid.uuid4()


class FakeStorage:
    configured = True

    def __init__(self) -> None:
        self.stored: list[str] = []
        self.deleted: list[str] = []
        self.links: list[tuple[str, int | None]] = []
        self.fail_delete = False

    async def store(self, media, *, prefix="media", original_url=None):
        key = f"{prefix}/{len(self.stored)}.jpg"
        self.stored.append(key)
        return type("S", (), {"storage_key": key})()

    def signed_url(self, key, *, expires_in=None):
        self.links.append((key, expires_in))
        return f"https://signed.example/{key}?sig=1"

    async def delete_objects(self, keys):
        if self.fail_delete:
            raise RuntimeError("bucket down")
        self.deleted.extend(keys)
        return []


class FakeIG:
    CAROUSEL_MAX = 10

    def __init__(self) -> None:
        self.published: list[tuple[list[str], str | None]] = []
        self.fail: Exception | None = None

    async def publish_post(self, credentials, image_urls, caption=None):
        if self.fail:
            raise self.fail
        self.published.append((list(image_urls), caption))
        return "new_post_1"


@pytest.fixture
def fakes(monkeypatch):
    storage, ig = FakeStorage(), FakeIG()
    synced: list[int] = []

    async def fake_sync(session, tenant_id, credentials, *, limit=25):
        synced.append(limit)
        return 1

    monkeypatch.setattr(ss, "get_storage", lambda: storage)
    monkeypatch.setattr(ss, "instagram_adapter", ig)
    monkeypatch.setattr(SocialService, "sync_posts", staticmethod(fake_sync))
    return storage, ig, synced


async def _publish(pictures, caption="hi"):
    return await SocialService.publish_post(None, TENANT, CREDS, pictures, caption)


async def test_a_photo_is_stored_linked_published_and_then_removed(fakes) -> None:
    storage, ig, synced = fakes
    assert await _publish([JPEG]) == "new_post_1"
    assert len(ig.published) == 1 and ig.published[0][1] == "hi"
    assert ig.published[0][0][0].startswith("https://signed.example/")
    assert storage.deleted == storage.stored  # nothing left behind
    assert synced == [5]  # the new post is pulled into the list


async def test_a_carousel_keeps_the_pictures_in_the_order_given(fakes) -> None:
    storage, ig, _ = fakes
    await _publish([JPEG + bytes([i]) for i in range(3)])
    assert [u.split("/")[-1].split("?")[0] for u in ig.published[0][0]] == [
        "0.jpg",
        "1.jpg",
        "2.jpg",
    ]


async def test_the_picture_link_is_short_lived_and_the_files_are_private(fakes) -> None:
    storage, _, _ = fakes
    await _publish([JPEG])
    assert all(ttl == ss.PICTURE_LINK_SECONDS and ttl <= 900 for _, ttl in storage.links)
    assert all(k.startswith(f"social-outbox/{TENANT}/") for k in storage.stored)


@pytest.mark.parametrize(
    ("pictures", "why"),
    [
        ([], "at least one"),
        ([JPEG] * 11, "at most 10"),
        ([b"\x89PNG\r\n\x1a\n" + b"x" * 40], "not a JPEG"),
        ([b"GIF89a" + b"x" * 40], "not a JPEG"),
        ([b"<html>not a picture</html>"], "not a JPEG"),
        ([JPEG, b"RIFFxxxxWEBP"], "picture 2 is not a JPEG"),
        ([JPEG + b"x" * ss.MAX_PICTURE_BYTES], "larger than 8 MB"),
    ],
)
async def test_what_instagram_refuses_is_refused_before_anything_is_stored(
    fakes, pictures, why
) -> None:
    storage, ig, _ = fakes
    with pytest.raises(ValidationError, match=why):
        await _publish(pictures)
    assert storage.stored == [] and ig.published == []


async def test_a_caption_over_2200_characters_is_refused_before_storing(fakes) -> None:
    storage, _, _ = fakes
    with pytest.raises(ValidationError, match="2,200"):
        await _publish([JPEG], caption="x" * 2201)
    assert storage.stored == []


async def test_a_blank_caption_is_no_caption(fakes) -> None:
    _, ig, _ = fakes
    await _publish([JPEG], caption="   ")
    assert ig.published[0][1] is None


async def test_when_instagram_refuses_the_temporary_files_are_still_removed(fakes) -> None:
    storage, ig, synced = fakes
    ig.fail = ExternalProviderError("instagram said no")
    with pytest.raises(ExternalProviderError):
        await _publish([JPEG, JPEG])
    assert storage.stored and storage.deleted == storage.stored
    assert synced == []  # nothing recorded for a post that never happened


async def test_the_adapters_own_refusal_becomes_a_validation_error(fakes) -> None:
    _, ig, _ = fakes
    ig.fail = ValueError("every picture must be a public https link")
    with pytest.raises(ValidationError, match="public https"):
        await _publish([JPEG])


async def test_a_cleanup_failure_never_hides_a_post_that_went_live(fakes) -> None:
    storage, _, _ = fakes
    storage.fail_delete = True
    assert await _publish([JPEG]) == "new_post_1"


async def test_a_refresh_failure_never_hides_a_post_that_went_live(fakes, monkeypatch) -> None:
    async def boom(*a, **k):
        raise ExternalProviderError("list failed")

    monkeypatch.setattr(SocialService, "sync_posts", staticmethod(boom))
    assert await _publish([JPEG]) == "new_post_1"


async def test_without_file_storage_it_says_so_and_calls_nothing(fakes) -> None:
    storage, ig, _ = fakes
    storage.configured = False
    with pytest.raises(ConflictError, match="storage"):
        await _publish([JPEG])
    assert ig.published == []


def test_a_browser_data_url_and_plain_base64_both_decode() -> None:
    raw = base64.b64encode(JPEG).decode()
    assert _decode_picture(raw, 1) == JPEG
    assert _decode_picture("data:image/jpeg;base64," + raw, 1) == JPEG


def test_broken_or_oversized_base64_is_a_clear_error_not_a_crash() -> None:
    with pytest.raises(ValidationError, match="not valid base64"):
        _decode_picture("***not base64***", 2)
    with pytest.raises(ValidationError, match="larger than 8 MB"):
        _decode_picture("A" * (ss.MAX_PICTURE_BYTES * 2), 1)
