"""Facebook Page content through the Pages Graph API (posts, comments, insights).

Messaging stays in `facebook.py`; this is everything the Page does in public. Every limit
below is Meta's own, from "Pages API: Posts", "Comments" and "Page Insights":

* a scheduled post goes live between 10 minutes and 30 days after the request;
* an app may EDIT only a post it published itself (Meta refuses the rest);
* the old reach/impression/fan metrics were removed and the API answers them with an
  "invalid metric" error, so only the replacements are ever requested.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.core.circuit_breaker import PROVIDER_MESSENGER, get_breaker
from app.core.errors import ExternalProviderError
from app.core.instagram_version import INSTAGRAM_API_VERSION
from app.modules.conversations.gateway.base import ProviderCredentials, parse_provider_body

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
    "parent{id},permalink_url,can_hide,can_remove,can_reply_privately"
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


def check_metrics(metrics: list[str]) -> list[str]:
    bad = [m for m in metrics if m in REMOVED_METRICS]
    if bad:
        raise ValueError(f"Meta removed these metrics: {', '.join(bad)}")
    return metrics


class FacebookPagesClient:
    def __init__(self, *, api_version: str = INSTAGRAM_API_VERSION):
        self._base = f"https://graph.facebook.com/{api_version}"

    @staticmethod
    def _creds(credentials: ProviderCredentials) -> tuple[str, str]:
        token = credentials.get("api_key")
        page_id = credentials.get("account_id")
        if not token or not page_id:
            raise ExternalProviderError("facebook integration missing api_key or account_id")
        return str(token), str(page_id)

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
        schedule_at: datetime | int | None = None,
        _client=None,
    ) -> str:
        """Publish now, or schedule. A photo goes to /photos, everything else to /feed."""
        message = (message or "").strip() or None
        if not (message or link or photo_url):
            raise ValueError("a post needs text, a link or a picture")
        if message and len(message) > MAX_POST_CHARS:
            raise ValueError(f"a post is at most {MAX_POST_CHARS:,} characters")
        if photo_url and link:
            raise ValueError("a post carries a picture or a link, not both")
        _, page_id = self._creds(credentials)
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
        return str(body.get("post_id") or body.get("id"))

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
        _client=None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "fields": f"{COMMENT_FIELDS},comments.limit(25){{{COMMENT_FIELDS}}}",
            "limit": max(1, min(limit, 100)),
            "order": "chronological",
            "filter": "toplevel",
        }
        if after:
            params["after"] = after
        body = await self._graph(
            "GET", f"{object_id}/comments", credentials, params=params, _client=_client
        )
        return self._page(body)

    async def comment(
        self, credentials: ProviderCredentials, object_id: str, text: str, _client=None
    ) -> str:
        """A comment on a post, or a reply when `object_id` is a comment."""
        text = text.strip()
        if not text:
            raise ValueError("a comment cannot be empty")
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

    async def like(
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
