"""Object storage — S3-compatible persistence for channel media.

Channel media URLs (WhatsApp especially) EXPIRE within hours, so media must be
fetched to our own storage during ingest. When S3 is not configured this
degrades to pass-through with a loud warning (dev only).

This module is a dumb port: it moves bytes, it does NOT screen them. Inbound
media is untrusted, so callers MUST use the two steps deliberately —

    fetched = await storage.fetch(url, max_bytes=MAX_MEDIA_BYTES)
    <screen fetched.content_type / size>   # e.g. MediaService's policy
    stored = await storage.store(fetched, original_url=url)

`fetch` + `store` are separate for exactly that reason: screening has to happen
BEFORE anything is written to the bucket. There is deliberately no one-call
`fetch-and-store` helper, because such a helper looks safe and is not — the
screened path lives in `app.modules.conversations.media.MediaService`.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.core.circuit_breaker import STORAGE_OBJECTS, get_breaker
from app.core.config import get_settings
from app.core.errors import ValidationError
from app.core.net_guard import assert_public_url

logger = logging.getLogger(__name__)

# Ceiling on a single inbound media object. Applied WHILE streaming, so a
# provider (or a malicious media URL) cannot make us buffer an unbounded body
# in memory and OOM the ingest worker. 25 MiB covers WhatsApp (16 MB) and
# Telegram (20 MB) with headroom.
MAX_MEDIA_BYTES = 25 * 1024 * 1024

# Storage keys are ours, never derived from a provider-supplied filename. The
# extension comes from the (untrusted) Content-Type, so it is constrained to a
# safe alphabet; anything else falls back to "bin".
_EXTENSION_RE = re.compile(r"^[a-z0-9]{1,10}$")


@dataclass
class FetchedMedia:
    """Bytes pulled from a provider URL, before any policy decision."""

    data: bytes
    content_type: str | None
    checksum: str  # sha256 hex of data


@dataclass
class StoredMedia:
    url: str  # durable URL (our bucket) or the original if pass-through
    content_type: str | None
    bytes_written: int
    durable: bool  # False when we could only keep the expiring original
    storage_key: str | None = None  # our object key, None when pass-through
    checksum: str | None = None  # sha256 hex of the stored bytes


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

    async def fetch(
        self, url: str, *, max_bytes: int | None = MAX_MEDIA_BYTES
    ) -> FetchedMedia:
        """Download a provider media URL as a bounded, SSRF-checked stream.

        Routed through the process-wide `storage.objects` breaker so a dead or
        degraded provider stops being hammered: once open, the download is not
        attempted at all and `CircuitOpenError` is raised instead. Callers that
        treat media as a bonus (see `conversations.media`) already contain that
        error, so an open breaker costs the attachment, never the message.

        S6: the URL comes from a channel payload, i.e. from the internet, so
        every hop is validated before we fetch it — otherwise a crafted media
        URL would make the worker fetch internal endpoints on the attacker's
        behalf (SSRF).

        Redirects are followed MANUALLY so every hop is checked:
        `follow_redirects=True` validated only the first URL, and a public host
        answering `302 Location: http://169.254.169.254/...` was followed
        straight to the cloud metadata service.

        `max_bytes` is enforced on the stream itself, not just on
        Content-Length (which a hostile server can understate or omit), so an
        oversized body is aborted mid-download instead of being buffered.
        """
        return await get_breaker(STORAGE_OBJECTS).call(self._download, url, max_bytes)

    async def _download(self, url: str, max_bytes: int | None) -> FetchedMedia:
        current = url
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            for _hop in range(self.MAX_REDIRECTS + 1):
                assert_public_url(current)
                async with client.stream("GET", current) as response:
                    if response.is_redirect and response.headers.get("location"):
                        current = urljoin(current, response.headers["location"])
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type")

                    if max_bytes is not None:
                        declared = response.headers.get("content-length")
                        if declared:
                            try:
                                declared_bytes = int(declared)
                            except ValueError:
                                # Unparseable header is not fatal: the streaming
                                # cap below still applies.
                                declared_bytes = None
                            if declared_bytes is not None and declared_bytes > max_bytes:
                                raise ValidationError(
                                    "media exceeds the size limit",
                                    details={"max_bytes": max_bytes},
                                )

                    digest = hashlib.sha256()
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if max_bytes is not None and total > max_bytes:
                            raise ValidationError(
                                "media exceeds the size limit",
                                details={"max_bytes": max_bytes},
                            )
                        digest.update(chunk)
                        chunks.append(chunk)
                    return FetchedMedia(
                        data=b"".join(chunks),
                        content_type=content_type,
                        checksum=digest.hexdigest(),
                    )
        raise ValidationError("too many redirects while fetching media")

    def _extension(self, content_type: str | None) -> str:
        """Derive a safe file extension from a (provider-supplied) media type.

        Only the subtype of a well-formed `type/subtype` is considered, and it
        must be a short alphanumeric token. Anything else — `image/svg+xml`,
        a path fragment, a header-injection attempt — becomes "bin". The key
        itself is always `{prefix}/{uuid4().hex}.{ext}`, so a provider can
        never influence the path.
        """
        mime = (content_type or "").split(";")[0].strip().lower()
        if "/" not in mime:
            return "bin"
        subtype = mime.split("/", 1)[1]
        return subtype if _EXTENSION_RE.match(subtype) else "bin"

    async def store(
        self,
        media: FetchedMedia,
        *,
        prefix: str = "media",
        original_url: str | None = None,
    ) -> StoredMedia:
        """Persist already-fetched bytes durably.

        Split from `fetch` so a caller can screen the bytes (content type,
        size) BEFORE anything is written to the bucket — policy must not run
        after the object is already stored.
        """
        if not self.configured:
            logger.warning("storage.s3_not_configured — keeping expiring URL only")
            return StoredMedia(
                url=original_url or "",
                content_type=media.content_type,
                bytes_written=0,
                durable=False,
                storage_key=None,
                checksum=media.checksum,
            )

        key = f"{prefix}/{uuid.uuid4().hex}.{self._extension(media.content_type)}"
        import asyncio

        # `put_object` is SYNCHRONOUS boto3, so the blocking call is handed to
        # `asyncio.to_thread` — the callable, not a pre-made coroutine, is what
        # goes to the breaker, which keeps the thread-pool hop AND the breaker's
        # failure accounting (an open breaker means boto3 is never entered).
        await get_breaker(STORAGE_OBJECTS).call(
            asyncio.to_thread,
            self._s3().put_object,
            Bucket=self._bucket,
            Key=key,
            Body=media.data,
            ContentType=media.content_type or "application/octet-stream",
        )
        return StoredMedia(
            url=self.public_url(key),
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=True,
            storage_key=key,
            checksum=media.checksum,
        )

_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = ObjectStorage()
    return _storage
