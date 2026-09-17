"""Object storage — S3-compatible persistence for channel media.

Channel media URLs (WhatsApp especially) EXPIRE within hours, so media must be
fetched to our own storage during ingest. When S3 is not configured this
degrades to pass-through with a loud warning (dev only).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

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

    async def persist_from_url(self, url: str, *, prefix: str = "media") -> StoredMedia:
        """Download a provider media URL and store it durably."""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
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
