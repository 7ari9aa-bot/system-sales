"""Object storage — S3-compatible persistence for channel media.

Channel media URLs (WhatsApp especially) EXPIRE within hours, so media must be
fetched to our own storage during ingest. When S3 is not configured this
degrades to pass-through with a loud warning (dev only).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.net_guard import assert_public_url

logger = logging.getLogger(__name__)


@dataclass
class StoredMedia:
    url: str  # durable URL (our bucket) or the original if pass-through
    content_type: str | None
    bytes_written: int
    durable: bool  # False when we could only keep the expiring original


class ObjectStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint
        self._region = settings.s3_region
        self._key = settings.s3_access_key_id
        self._secret = settings.s3_secret_access_key
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self._bucket and self._key and self._secret)

    def _s3(self):
        if self._client is None:
            import boto3  # lazy: only needed when storage is configured

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint or None,
                region_name=self._region or "us-east-1",
                aws_access_key_id=self._key,
                aws_secret_access_key=self._secret,
            )
        return self._client

    def public_url(self, key: str) -> str:
        if self._endpoint:
            return f"{self._endpoint.rstrip('/')}/{self._bucket}/{key}"
        return f"https://{self._bucket}.s3.{self._region or 'us-east-1'}.amazonaws.com/{key}"

    MAX_REDIRECTS = 3

    async def _fetch_validated(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """Follow redirects MANUALLY so every hop is SSRF-checked.

        `follow_redirects=True` validated only the first URL: a public host
        that answers `302 Location: http://169.254.169.254/...` was followed
        straight to the cloud metadata service, which is a complete SSRF
        bypass of the guard.
        """
        current = url
        for _hop in range(self.MAX_REDIRECTS + 1):
            assert_public_url(current)
            response = await client.get(current)
            location = response.headers.get("location")
            if response.is_redirect and location:
                current = urljoin(current, location)
                continue
            return response
        raise ValidationError("too many redirects while fetching media")

    async def persist_from_url(self, url: str, *, prefix: str = "media") -> StoredMedia:
        """Download a provider media URL and store it durably.

        S6: the URL comes from a channel payload, i.e. from the internet, so
        it is validated before we fetch it — otherwise a crafted media URL
        would make the worker fetch internal endpoints on the attacker's
        behalf (SSRF).
        """
        assert_public_url(url)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await self._fetch_validated(client, url)
            response.raise_for_status()
            content = response.content
            content_type = response.headers.get("content-type")

        if not self.configured:
            logger.warning("storage.s3_not_configured — keeping expiring URL only")
            return StoredMedia(url=url, content_type=content_type, bytes_written=0, durable=False)

        ext = (content_type or "").split("/")[-1].split(";")[0] or "bin"
        key = f"{prefix}/{uuid.uuid4().hex}.{ext}"
        import asyncio

        await asyncio.to_thread(
            self._s3().put_object,
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
        )
        return StoredMedia(
            url=self.public_url(key),
            content_type=content_type,
            bytes_written=len(content),
            durable=True,
        )


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = ObjectStorage()
    return _storage
