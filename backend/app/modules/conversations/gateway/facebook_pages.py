"""Facebook Page content through the Pages Graph API (posts, comments, insights).

Messaging stays in `facebook.py`; this is everything the Page does in public. Every limit
below is Meta's own, from "Pages API: Posts", "Comments" and "Page Insights":

* a scheduled post goes live between 10 minutes and 30 days after the request;
* an app may EDIT only a post it published itself (Meta refuses the rest);
* the old reach/impression/fan metrics were removed and the API answers them with an
  "invalid metric" error, so only the replacements are ever requested.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from app.core.circuit_breaker import PROVIDER_MESSENGER, get_breaker
from app.core.errors import ExternalProviderError
from app.core.instagram_version import INSTAGRAM_API_VERSION
from app.modules.conversations.gateway.base import ProviderCredentials, parse_provider_body

#: Where Meta takes the bytes of a Reel or a Story video (every other call stays on graph).
UPLOAD_HOST = "https://rupload.facebook.com/video-upload"
#: A video is processed after the upload; how long to wait for it, and how often to ask.
PROCESSING_TIMEOUT_SECONDS = 180
PROCESSING_POLL_SECONDS = 3

SCHEDULE_MIN_SECONDS = 10 * 60
SCHEDULE_MAX_SECONDS = 30 * 24 * 3600
MAX_POST_CHARS = 63206  # Facebook's own limit for a post's text

POST_FIELDS = (
    "id,message,created_time,permalink_url,full_picture,status_type,is_published,"
    "scheduled_publish_time,attachments{media_type,url},"
    "shares,comments.summary(true).limit(0),reactions.summary(true).limit(0)"
)
COMMENT_FIELDS = (
    "id,message,created_time,from{id,name},like_count,comment_count,is_hidden,"
    "parent{id},permalink_url,can_hide,can_remove,can_reply_privately,user_likes"
)

# Replacements for the removed metrics (Meta, "Deprecated Page Insights Metrics").
PAGE_METRICS = ("page_follows", "page_media_view", "page_post_engagements")
POST_METRICS = (
    "post_media_view",
    "post_reactions_like_total",
    "post_reactions_love_total",
    "post_reactions_wow_total",
    "post_reactions_haha_total",
    "post_reactions_sorry_total",
    "post_reactions_anger_total",
)
REMOVED_METRICS = frozenset(
    {
        "page_fans", "page_fan_adds", "page_fan_removes", "page_impressions",
        "page_impressions_unique", "page_impressions_paid", "page_engaged_users",
        "post_impressions", "post_impressions_unique", "post_impressions_paid",
        "post_impressions_organic", "page_posts_impressions",
    }
)  # fmt: skip


def check_schedule(when: datetime | int, *, now: float | None = None) -> int:
    """The UNIX time to send Meta, or ValueError when it falls outside the allowed window."""
    stamp = int(when.timestamp()) if isinstance(when, datetime) else int(when)
    delta = stamp - (time.time() if now is None else now)
    if delta < SCHEDULE_MIN_SECONDS:
        raise ValueError("a scheduled post must go live at least 10 minutes from now")
    if delta > SCHEDULE_MAX_SECONDS:
        raise ValueError("a scheduled post must go live within 30 days")
    return stamp


def mention_tag(psids: list[str]) -> str:
    """Meta's `@[PSID]` tag (`@[1,2]` for several) that notifies the people it names.

    The ids come from comments already on the Page, never from typed text, so anything that is not a
    plain number is refused before a request is made. One person is tagged once.
    """
    seen: list[str] = []
    for raw in psids or []:
        value = str(raw).strip()
        if not value.isdigit():
            raise ValueError("a mention needs the numeric id of someone who commented on the Page")
        if value not in seen:
            seen.append(value)
    if not seen:
        raise ValueError("a mention needs at least one person to tag")
    return "@[" + ",".join(seen) + "]"


#: The Page fields an owner may edit, and the permission each write needs. A field Meta does not
#: expose at all is listed with ``exposed=False`` so a screen says "read-only" instead of drawing a
#: box that cannot save. Verified against Meta's Page fields reference; nothing invented.
PAGE_FIELD_MATRIX: dict[str, dict[str, Any]] = {
    "about": {"editable": True, "write_scope": "pages_manage_metadata"},
    "description": {"editable": True, "write_scope": "pages_manage_metadata"},
    "website": {"editable": True, "write_scope": "pages_manage_metadata"},
    "phone": {"editable": True, "write_scope": "pages_manage_metadata"},
    "emails": {"editable": True, "write_scope": "pages_manage_metadata", "note": "a list"},
    "category": {"editable": True, "write_scope": "pages_manage_metadata"},
    "hours": {
        "editable": True,
        "write_scope": "pages_manage_metadata",
        "note": "structured JSON per day, not free text",
    },
    "name": {"editable": False, "note": "renamed through Meta's own review flow, not here"},
    "id": {"editable": False},
    "followers_count": {"editable": False, "note": "counted by Meta"},
    "fan_count": {"editable": False, "note": "counted by Meta"},
    "verification_status": {
        "editable": False,
        "exposed": False,
        "note": "Business Suite shows it; the API does not expose verification",
    },
    "rating": {
        "editable": False,
        "exposed": False,
        "note": "Page ratings have no API surface",
    },
}

#: What a Page edit form may send, in display order.
EDITABLE_PAGE_FIELDS: tuple[str, ...] = tuple(
    name for name, spec in PAGE_FIELD_MATRIX.items() if spec.get("editable")
)


def check_metrics(metrics: list[str]) -> list[str]:
    bad = [m for m in metrics if m in REMOVED_METRICS]
    if bad:
        raise ValueError(f"Meta removed these metrics: {', '.join(bad)}")
    return metrics


def page_token_and_id(credentials: ProviderCredentials) -> tuple[str, str]:
    """The Page token and Page id of a stored Facebook channel, whichever way it was saved.

    The connection spec and the OAuth callback store a ``facebook`` channel as
    ``credentials.page_access_token`` with the page in ``config.account_id`` (the
    Messenger gateway already accepts both token keys). This client only ever read
    ``api_key``, so a correctly connected Page answered "Facebook is not connected" on
    every /facebook screen. Empty strings when either part is missing.
    """
    token = credentials.get("page_access_token") or credentials.get("api_key") or ""
    page_id = credentials.get("account_id") or credentials.get("page_id") or ""
    return str(token), str(page_id)


#: Pictures in one Page post. Meta takes more, but a longer album fails often and half-uploads.
MAX_PHOTOS_PER_POST = 10

#: The reaction kinds Meta counts, in the order Facebook shows them.
REACTION_KINDS = ("LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY")


def _published_post_id(body: dict[str, Any]) -> str:
    """The id Meta gave the new post, or a refusal.

    ``str(body.get("post_id") or body.get("id"))`` turned an answer with neither key into the
    text ``"None"``, which then looked like a post id: it was stored, shown, and later used to
    comment on or delete a post that does not exist. A publish that returned no id has not been
    shown to have worked, so it says so.
    """
    post_id = (body.get("post_id") or body.get("id")) if isinstance(body, dict) else None
    if not post_id:
        raise ExternalProviderError("facebook returned no id for the new post")
    return str(post_id)


class FacebookPagesClient:
    def __init__(self, *, api_version: str = INSTAGRAM_API_VERSION):
        self._base = f"https://graph.facebook.com/{api_version}"

    @staticmethod
    def _creds(credentials: ProviderCredentials) -> tuple[str, str]:
        token, page_id = page_token_and_id(credentials)
        if not token or not page_id:
            raise ExternalProviderError("facebook integration missing page token or page id")
        return token, page_id

    async def _graph(
        self,
        method: str,
        path: str,
        credentials: ProviderCredentials,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        token, _ = self._creds(credentials)
        url = f"{self._base}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}

        async def _call() -> dict[str, Any]:
            if _client is not None:
                resp = await _client.request(method, url, headers=headers, params=params, data=data)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.request(
                        method, url, headers=headers, params=params, data=data
                    )
            body = parse_provider_body(resp, f"facebook {method} {path}")
            if resp.status_code not in (200, 201) or "error" in body:
                err = body.get("error") if isinstance(body, dict) else None
                detail = (err or {}).get("message") if isinstance(err, dict) else str(body)[:200]
                raise ExternalProviderError(
                    f"facebook {method} {path} failed: HTTP {resp.status_code} - {detail}"
                )
            return body

        return await get_breaker(PROVIDER_MESSENGER).call(_call)

    @staticmethod
    def _page(body: dict[str, Any]) -> dict[str, Any]:
        paging = body.get("paging") or {}
        return {
            "items": body.get("data") or [],
            "next": (paging.get("cursors") or {}).get("after") if paging.get("next") else None,
        }

    # ---- the Page ----
    async def get_page(self, credentials: ProviderCredentials, _client=None) -> dict[str, Any]:
        _, page_id = self._creds(credentials)
        return await self._graph(
            "GET",
            page_id,
            credentials,
            params={
                "fields": "id,name,about,category,fan_count,followers_count,link,picture{url},"
                "cover{source},website,phone,emails,single_line_address,verification_status"
            },
            _client=_client,
        )

    # ---- posts ----
    async def list_posts(
        self,
        credentials: ProviderCredentials,
        *,
        limit: int = 25,
        after: str | None = None,
        scheduled: bool = False,
        _client=None,
    ) -> dict[str, Any]:
        _, page_id = self._creds(credentials)
        # Scheduled and unpublished posts live on their own edge, not in the public feed.
        edge = "scheduled_posts" if scheduled else "published_posts"
        params: dict[str, Any] = {"fields": POST_FIELDS, "limit": max(1, min(limit, 50))}
        if after:
            params["after"] = after
        body = await self._graph(
            "GET", f"{page_id}/{edge}", credentials, params=params, _client=_client
        )
        return self._page(body)

    async def publish_post(
        self,
        credentials: ProviderCredentials,
        *,
        message: str | None = None,
        link: str | None = None,
        photo_url: str | None = None,
        photo_urls: list[str] | None = None,
        schedule_at: datetime | int | None = None,
        _client=None,
    ) -> str:
        """Publish now, or schedule. One photo goes to /photos, several to /feed as attached media,
        everything else to /feed."""
        message = (message or "").strip() or None
        photos = [u for u in (photo_urls or []) if u]
        if photo_url and photos:
            raise ValueError(
                "a post carries a picture or a link, not both: send one form of picture"
            )
        if len(photos) > MAX_PHOTOS_PER_POST:
            raise ValueError(f"a post carries at most {MAX_PHOTOS_PER_POST} pictures")
        if len(photos) == 1:
            photo_url, photos = photos[0], []
        if not (message or link or photo_url or photos):
            raise ValueError("a post needs text, a link or a picture")
        if message and len(message) > MAX_POST_CHARS:
            raise ValueError(f"a post is at most {MAX_POST_CHARS:,} characters")
        if (photo_url or photos) and link:
            raise ValueError("a post carries a picture or a link, not both")
        _, page_id = self._creds(credentials)
        if photos:
            return await self._publish_album(
                credentials, page_id, message, photos, schedule_at, _client
            )
        data: dict[str, Any] = {}
        if message:
            data["caption" if photo_url else "message"] = message
        if link:
            data["link"] = link
        if photo_url:
            data["url"] = photo_url
        if schedule_at is not None:
            data["published"] = "false"
            data["scheduled_publish_time"] = str(check_schedule(schedule_at))
        edge = "photos" if photo_url else "feed"
        body = await self._graph(
            "POST", f"{page_id}/{edge}", credentials, data=data, _client=_client
        )
        return _published_post_id(body)

    async def _publish_album(
        self, credentials, page_id: str, message, photos: list[str], schedule_at, _client
    ) -> str:
        """Several pictures: upload each unpublished, then one /feed post lists their ids.

        Meta has no single call for it. The time to publish belongs to the post, not to the photos,
        so a scheduled album schedules the feed post and leaves the uploads unpublished.
        """
        when = check_schedule(schedule_at) if schedule_at is not None else None
        ids: list[str] = []
        for url in photos:
            up = await self._graph(
                "POST",
                f"{page_id}/photos",
                credentials,
                data={"url": url, "published": "false"},
                _client=_client,
            )
            if not up.get("id"):
                raise ValueError("Facebook did not accept one of the pictures")
            ids.append(str(up["id"]))
        data: dict[str, Any] = {
            f"attached_media[{i}]": _json({"media_fbid": pid}) for i, pid in enumerate(ids)
        }
        if message:
            data["message"] = message
        if when is not None:
            data["published"] = "false"
            data["scheduled_publish_time"] = str(when)
        body = await self._graph("POST", f"{page_id}/feed", credentials, data=data, _client=_client)
        return _published_post_id(body)

    async def update_post(
        self, credentials: ProviderCredentials, post_id: str, message: str, _client=None
    ) -> None:
        message = message.strip()
        if not message:
            raise ValueError("the text cannot be empty")
        await self._graph("POST", post_id, credentials, data={"message": message}, _client=_client)

    async def delete_post(
        self, credentials: ProviderCredentials, post_id: str, _client=None
    ) -> None:
        await self._graph("DELETE", post_id, credentials, _client=_client)

    # ---- comments ----
    async def list_comments(
        self,
        credentials: ProviderCredentials,
        object_id: str,
        *,
        limit: int = 50,
        after: str | None = None,
        order: str = "oldest",
        _client=None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fields": f"{COMMENT_FIELDS},comments.limit(25){{{COMMENT_FIELDS}}}",
            "limit": max(1, min(limit, 100)),
            "filter": "toplevel",
        }
        # Facebook offers "Most relevant" and "Newest" above a post's comments. `ranked` asks
        # Meta to rank, so it sends no `order` at all: any explicit value overrides the ranking.
        # Meta may still rank regardless when it can, so `oldest` is a preference, not a
        # guarantee.
        if order == "oldest":
            params["order"] = "chronological"
        elif order == "newest":
            params["order"] = "reverse_chronological"
        elif order != "ranked":
            raise ValueError(f"unknown comment order {order!r}: use oldest, newest or ranked")
        if after:
            params["after"] = after
        body = await self._graph(
            "GET", f"{object_id}/comments", credentials, params=params, _client=_client
        )
        return self._page(body)

    async def comment(
        self,
        credentials: ProviderCredentials,
        object_id: str,
        text: str,
        *,
        mention: list[str] | None = None,
        _client=None,
    ) -> str:
        """A comment on a post, or a reply when `object_id` is a comment.

        `mention` tags people who commented on the Page (Pages API: Comments and @mentions); Meta
        notifies them. The tag leads the text, as Facebook's own reply box puts it.
        """
        text = text.strip()
        if not text:
            raise ValueError("a comment cannot be empty")
        if mention:
            text = f"{mention_tag(mention)} {text}"
        body = await self._graph(
            "POST", f"{object_id}/comments", credentials, data={"message": text}, _client=_client
        )
        return str(body.get("id"))

    async def set_comment_hidden(
        self, credentials: ProviderCredentials, comment_id: str, hidden: bool, _client=None
    ) -> None:
        await self._graph(
            "POST",
            comment_id,
            credentials,
            data={"is_hidden": "true" if hidden else "false"},
            _client=_client,
        )

    async def delete_comment(
        self, credentials: ProviderCredentials, comment_id: str, _client=None
    ) -> None:
        await self._graph("DELETE", comment_id, credentials, _client=_client)

    async def get_reaction_breakdown(
        self, credentials: ProviderCredentials, object_id: str, _client=None
    ) -> dict[str, int]:
        """A post's (or comment's) reactions by kind, in Facebook's order, in ONE request.

        Meta's Object Reactions edge counts one kind per call (`reactions.type(LOVE)`), so each kind
        is an aliased edge of the same read. Counts only (`limit(0)`), never the people. A Page can
        read all six kinds but write only a like, so this feeds the display, not a reaction picker.
        """
        edges = ",".join(
            f"reactions.type({kind}).limit(0).summary(true).as({kind.lower()})"
            for kind in REACTION_KINDS
        )
        body = await self._graph(
            "GET", object_id, credentials, params={"fields": edges}, _client=_client
        )
        return {
            kind: int(((body.get(kind.lower()) or {}).get("summary") or {}).get("total_count") or 0)
            for kind in REACTION_KINDS
        }

    async def set_like(
        self, credentials: ProviderCredentials, object_id: str, liked: bool, _client=None
    ) -> None:
        """The Page likes (or un-likes) a post or comment, as the Page."""
        await self._graph(
            "POST" if liked else "DELETE", f"{object_id}/likes", credentials, _client=_client
        )

    async def private_reply(
        self, credentials: ProviderCredentials, comment_id: str, text: str, _client=None
    ) -> str:
        """A Messenger message to the person who commented (one per comment, within 7 days)."""
        text = text.strip()
        if not text:
            raise ValueError("a message cannot be empty")
        _, page_id = self._creds(credentials)
        body = await self._graph(
            "POST",
            f"{page_id}/messages",
            credentials,
            data={
                "recipient": f'{{"comment_id":"{comment_id}"}}',
                "message": f'{{"text":{_json(text)}}}',
            },
            _client=_client,
        )
        return str(body.get("message_id") or "")

    # ---- Reels and Stories ----
    async def _start_video(
        self, credentials: ProviderCredentials, edge: str, _client=None
    ) -> tuple[str, str]:
        """Open an upload session. Returns (video_id, upload_url)."""
        _, page_id = self._creds(credentials)
        body = await self._graph(
            "POST",
            f"{page_id}/{edge}",
            credentials,
            data={"upload_phase": "start"},
            _client=_client,
        )
        video_id = str(body.get("video_id") or "")
        if not video_id:
            raise ExternalProviderError(f"facebook {edge} start returned no video id")
        return video_id, str(body.get("upload_url") or f"{UPLOAD_HOST}/{video_id}")

    async def _hand_over_video(
        self,
        credentials: ProviderCredentials,
        upload_url: str,
        file_url: str,
        _client=None,
    ) -> None:
        """Tell Meta where to fetch the video from; it pulls the file itself."""
        token, _ = self._creds(credentials)
        if not upload_url.startswith(UPLOAD_HOST):
            # the host is part of Meta's contract: never send a token to any other address
            raise ExternalProviderError("facebook returned an unexpected upload address")
        headers = {"Authorization": f"OAuth {token}", "file_url": file_url}

        async def _call() -> None:
            if _client is not None:
                resp = await _client.post(upload_url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(upload_url, headers=headers)
            body = parse_provider_body(resp, "facebook video upload")
            if resp.status_code != 200 or not body.get("success"):
                err = body.get("error") if isinstance(body, dict) else None
                detail = (err or {}).get("message") if isinstance(err, dict) else str(body)[:200]
                raise ExternalProviderError(
                    f"facebook video upload failed: HTTP {resp.status_code} - {detail}"
                )

        await get_breaker(PROVIDER_MESSENGER).call(_call)

    async def video_status(
        self, credentials: ProviderCredentials, video_id: str, _client=None
    ) -> dict[str, Any]:
        body = await self._graph(
            "GET", video_id, credentials, params={"fields": "status"}, _client=_client
        )
        return body.get("status") or {}

    async def _wait_until_processed(
        self, credentials: ProviderCredentials, video_id: str, _client=None, _sleep=None
    ) -> None:
        """Meta processes the video after the upload; publishing before it is done is refused.

        Stops at the first definite answer: an error Meta names (its message is passed on, e.g.
        "Resolution too low"), or the upload and processing both complete.
        """
        sleep = _sleep or asyncio.sleep
        waited = 0
        while True:
            status = await self.video_status(credentials, video_id, _client=_client)
            for phase in ("uploading_phase", "processing_phase", "publishing_phase"):
                err = (status.get(phase) or {}).get("error")
                if err:
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise ExternalProviderError(f"facebook could not process the video: {msg}")
            if status.get("video_status") in ("error", "upload_failed", "expired"):
                raise ExternalProviderError(
                    f"facebook could not process the video: {status.get('video_status')}"
                )
            done = ("complete", "completed")
            if (status.get("uploading_phase") or {}).get("status") in done and (
                status.get("processing_phase") or {}
            ).get("status") in done:
                return
            if waited >= PROCESSING_TIMEOUT_SECONDS:
                raise ExternalProviderError(
                    "facebook is still processing the video; try again later"
                )
            await sleep(PROCESSING_POLL_SECONDS)
            waited += PROCESSING_POLL_SECONDS

    async def publish_reel(
        self,
        credentials: ProviderCredentials,
        *,
        video_url: str,
        description: str | None = None,
        title: str | None = None,
        schedule_at: datetime | int | None = None,
        place: str | None = None,
        is_ai_generated: bool = False,
        _client=None,
        _sleep=None,
    ) -> str:
        """Publish a Reel from a link Meta can fetch. Returns the video id."""
        description = (description or "").strip() or None
        if description and len(description) > MAX_POST_CHARS:
            raise ValueError(f"a Reel's text is at most {MAX_POST_CHARS:,} characters")
        data: dict[str, Any] = {"upload_phase": "finish", "video_state": "PUBLISHED"}
        if schedule_at is not None:
            from app.modules.conversations.gateway.facebook_video import (
                REEL_SCHEDULE_MAX_SECONDS,
                REEL_SCHEDULE_MIN_SECONDS,
            )

            stamp = (
                int(schedule_at.timestamp())
                if isinstance(schedule_at, datetime)
                else int(schedule_at)
            )
            delta = stamp - time.time()
            if delta < REEL_SCHEDULE_MIN_SECONDS:
                raise ValueError("a scheduled Reel must go live at least 10 minutes from now")
            if delta > REEL_SCHEDULE_MAX_SECONDS:
                raise ValueError("a scheduled Reel must go live within 29 days")
            data["video_state"] = "SCHEDULED"
            data["scheduled_publish_time"] = str(stamp)
        if description:
            data["description"] = description
        if title and title.strip():
            data["title"] = title.strip()[:255]
        if place:
            data["place"] = place
        if is_ai_generated:
            data["is_ai_generated"] = "true"
        _, page_id = self._creds(credentials)
        video_id, upload_url = await self._start_video(credentials, "video_reels", _client=_client)
        await self._hand_over_video(credentials, upload_url, video_url, _client=_client)
        await self._wait_until_processed(credentials, video_id, _client=_client, _sleep=_sleep)
        data["video_id"] = video_id
        await self._graph("POST", f"{page_id}/video_reels", credentials, data=data, _client=_client)
        return video_id

    async def publish_video_story(
        self,
        credentials: ProviderCredentials,
        *,
        video_url: str,
        is_ai_generated: bool = False,
        _client=None,
        _sleep=None,
    ) -> str:
        """Publish a video Story from a link Meta can fetch. Returns the story's post id."""
        _, page_id = self._creds(credentials)
        video_id, upload_url = await self._start_video(
            credentials, "video_stories", _client=_client
        )
        await self._hand_over_video(credentials, upload_url, video_url, _client=_client)
        await self._wait_until_processed(credentials, video_id, _client=_client, _sleep=_sleep)
        data = {"video_id": video_id, "upload_phase": "finish"}
        if is_ai_generated:
            data["is_ai_generated"] = "true"
        body = await self._graph(
            "POST", f"{page_id}/video_stories", credentials, data=data, _client=_client
        )
        return str(body.get("post_id") or video_id)

    async def publish_photo_story(
        self, credentials: ProviderCredentials, *, photo_url: str, _client=None
    ) -> str:
        """Publish a photo Story: upload it unpublished, then turn it into a Story."""
        _, page_id = self._creds(credentials)
        photo = await self._graph(
            "POST",
            f"{page_id}/photos",
            credentials,
            data={"url": photo_url, "published": "false"},
            _client=_client,
        )
        photo_id = str(photo.get("id") or "")
        if not photo_id:
            raise ExternalProviderError("facebook returned no id for the story picture")
        body = await self._graph(
            "POST",
            f"{page_id}/photo_stories",
            credentials,
            data={"photo_id": photo_id},
            _client=_client,
        )
        return str(body.get("post_id") or photo_id)

    async def list_reels(
        self,
        credentials: ProviderCredentials,
        *,
        limit: int = 25,
        after: str | None = None,
        _client=None,
    ) -> dict[str, Any]:
        _, page_id = self._creds(credentials)
        params: dict[str, Any] = {
            "fields": "id,description,title,updated_time,permalink_url,picture,length",
            "limit": max(1, min(limit, 50)),
        }
        if after:
            params["after"] = after
        body = await self._graph(
            "GET", f"{page_id}/video_reels", credentials, params=params, _client=_client
        )
        return self._page(body)

    async def list_stories(
        self, credentials: ProviderCredentials, *, _client=None
    ) -> list[dict[str, Any]]:
        _, page_id = self._creds(credentials)
        body = await self._graph("GET", f"{page_id}/stories", credentials, _client=_client)
        return body.get("data") or []

    # ---- page fields ----
    async def update_page_fields(
        self, credentials: ProviderCredentials, values: dict[str, Any], _client=None
    ) -> dict[str, Any]:
        """Write the Page fields Meta allows, refusing a read-only or unknown field FIRST.

        Refusing before the call matters: a POST that names `name` or `verification_status` is
        rejected by Meta with a generic permission error that tells the owner nothing about which
        field was the problem.
        """
        if not values:
            raise ValueError("no fields to update")
        unknown = sorted(k for k in values if k not in EDITABLE_PAGE_FIELDS)
        if unknown:
            raise ValueError(f"these Page fields are not editable through the API: {', '.join(unknown)}")
        _, page_id = self._creds(credentials)
        return await self._graph("POST", page_id, credentials, data=values, _client=_client)

    # ---- post controls ----
    async def set_post_pinned(
        self, credentials: ProviderCredentials, post_id: str, pinned: bool, _client=None
    ) -> None:
        """Pin or unpin a post on the Page. Meta takes `is_pinned` on the post object."""
        await self._graph(
            "POST",
            post_id,
            credentials,
            data={"is_pinned": "true" if pinned else "false"},
            _client=_client,
        )

    async def set_post_hidden(
        self, credentials: ProviderCredentials, post_id: str, hidden: bool, _client=None
    ) -> None:
        """Hide or unhide a post from the timeline. The post still exists for its author."""
        await self._graph(
            "POST",
            post_id,
            credentials,
            data={"is_hidden": "true" if hidden else "false"},
            _client=_client,
        )

    # ---- insights ----
    async def get_page_insights(
        self,
        credentials: ProviderCredentials,
        *,
        since: int | None = None,
        until: int | None = None,
        _client=None,
    ) -> list[dict[str, Any]]:
        _, page_id = self._creds(credentials)
        params: dict[str, Any] = {
            "metric": ",".join(check_metrics(list(PAGE_METRICS))),
            "period": "day",
        }
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        body = await self._graph(
            "GET", f"{page_id}/insights", credentials, params=params, _client=_client
        )
        return body.get("data") or []

    async def get_post_insights(
        self, credentials: ProviderCredentials, post_id: str, _client=None
    ) -> list[dict[str, Any]]:
        params = {"metric": ",".join(check_metrics(list(POST_METRICS)))}
        body = await self._graph(
            "GET", f"{post_id}/insights", credentials, params=params, _client=_client
        )
        return body.get("data") or []


def _json(value: str) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


facebook_pages = FacebookPagesClient()
