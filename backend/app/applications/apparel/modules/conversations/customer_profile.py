"""Who an Instagram customer is: name, @handle, photo, follower facts.

Instagram's webhook names a customer only by a page-scoped number, so without this the
whole inbox is a list of numbers. The profile is read once, then refreshed rarely.

Rules:
  * a refusal is normal (someone who only commented has not consented), and a failure
    here NEVER stops the message that triggered it;
  * the photo link Instagram gives expires within days, so the image is copied into our own
    storage (same size and type checks as any inbound media) and only OUR key is kept;
  * a name the merchant typed is never overwritten; only a missing or numeric one is replaced.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.storage import get_storage
from app.applications.apparel.modules.conversations.gateway.base import ProviderCredentials
from app.applications.apparel.modules.conversations.gateway.instagram import instagram_adapter
from app.applications.apparel.modules.conversations.gateway.messenger import messenger_adapter
from app.applications.apparel.modules.conversations.media import check_media_policy

logger = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(days=7)
RETRY_AFTER = timedelta(hours=6)  # a refused or failed read is not retried on every message
MAX_AVATAR_BYTES = 2 * 1024 * 1024
_AVATAR_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})  # never svg, never gif


def customers():
    """The customers module's service, imported on first use (a module-scope import would cycle)."""
    from app.applications.apparel.modules.customers.service import CustomerService

    return CustomerService


def looks_like_an_id(name: str | None) -> bool:
    """True for no name, or one that is just the page-scoped number we stored as a placeholder."""
    n = (name or "").strip()
    return not n or n.isdigit()


def needs_refresh(extra: dict[str, Any] | None, now: datetime) -> bool:
    ex = extra or {}
    at = ex.get("profile_at")
    if not at:
        return True
    try:
        last = datetime.fromisoformat(at)
    except ValueError:
        return True
    wait = REFRESH_AFTER if ex.get("profile_ok") else RETRY_AFTER
    return now - last >= wait


class CustomerProfileService:
    @staticmethod
    async def enrich_instagram(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer: Any,
        credentials: dict,
        *,
        now: datetime | None = None,
        storage: Any = None,
    ) -> bool:
        """Fill in the customer's profile. Returns True when something was learned. Never raises."""
        now = now or datetime.now(UTC)
        try:
            identity = await customers().channel_identity(
                session, tenant_id, customer.id, "instagram"
            )
            if identity is None or not needs_refresh(identity.extra, now):
                return False
            extra = dict(identity.extra or {})
            creds = (
                credentials
                if isinstance(credentials, ProviderCredentials)
                else ProviderCredentials(config=credentials)
            )
            profile = await instagram_adapter.get_user_profile(creds, identity.external_id)
            extra["profile_at"] = now.isoformat()
            if profile is None:
                extra["profile_ok"] = False
                identity.extra = extra
                return False
            extra["profile_ok"] = True
            for src, dst in (
                ("username", "username"),
                ("verified", "verified"),
                ("follower_count", "follower_count"),
                ("follows_you", "follows_you"),
                ("you_follow", "you_follow"),
            ):
                if profile.get(src) is not None:
                    extra[dst] = profile[src]
            key = await CustomerProfileService._copy_avatar(profile.get("profile_pic"), storage)
            if key:
                extra["avatar_key"] = key
            identity.extra = extra
            better = profile.get("name") or profile.get("username")
            if better and looks_like_an_id(customer.name):
                customer.name = better
            return True
        except Exception:  # noqa: BLE001 - enrichment is a courtesy, the message must still land
            logger.warning("instagram profile enrichment failed", exc_info=True)
            return False

    @staticmethod
    async def enrich_instagram_for(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        credentials: dict,
        **kwargs: Any,
    ) -> bool | None:
        """`enrich_instagram` for a customer known only by id; None when it is not this tenant's."""
        customer = await customers().get_for_tenant(session, tenant_id, customer_id)
        if customer is None:
            return None
        return await CustomerProfileService.enrich_instagram(
            session, tenant_id, customer, credentials, **kwargs
        )

    @staticmethod
    async def enrich_messenger(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer: Any,
        credentials: dict,
        *,
        now: datetime | None = None,
        storage: Any = None,
    ) -> bool:
        """Messenger's turn: a PSID becomes a name and a face. True when something was learned.

        Same rules as Instagram — read once, retry rarely, never raise — because a Messenger
        webhook also names the sender only by a page-scoped number.
        """
        now = now or datetime.now(UTC)
        try:
            identity = await customers().channel_identity(
                session, tenant_id, customer.id, "messenger"
            )
            if identity is None or not needs_refresh(identity.extra, now):
                return False
            extra = dict(identity.extra or {})
            creds = (
                credentials
                if isinstance(credentials, ProviderCredentials)
                else ProviderCredentials(config=credentials)
            )
            profile = await messenger_adapter.get_user_profile(creds, identity.external_id)
            extra["profile_at"] = now.isoformat()
            if profile is None:
                extra["profile_ok"] = False
                identity.extra = extra
                return False
            extra["profile_ok"] = True
            key = await CustomerProfileService._copy_avatar(profile.get("profile_pic"), storage)
            if key:
                extra["avatar_key"] = key
            identity.extra = extra
            better = profile.get("name")
            if better and looks_like_an_id(customer.name):
                customer.name = better
            return True
        except Exception:  # noqa: BLE001 - enrichment is a courtesy, the message must still land
            logger.warning("messenger profile enrichment failed", exc_info=True)
            return False

    @staticmethod
    async def enrich_messenger_for(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        credentials: dict,
        **kwargs: Any,
    ) -> bool | None:
        """`enrich_messenger` for a customer known only by id; None when it is not this tenant's."""
        customer = await customers().get_for_tenant(session, tenant_id, customer_id)
        if customer is None:
            return None
        return await CustomerProfileService.enrich_messenger(
            session, tenant_id, customer, credentials, **kwargs
        )

    @staticmethod
    async def _copy_avatar(url: str | None, storage: Any = None) -> str | None:
        if not url:
            return None
        try:
            store = storage or get_storage()
            fetched = await store.fetch(url, max_bytes=MAX_AVATAR_BYTES)
            mime = check_media_policy(content_type=fetched.content_type, size=len(fetched.data))
            if mime not in _AVATAR_TYPES:
                return None
            stored = await store.store(fetched, prefix="avatars", original_url=url)
            return stored.storage_key if stored.durable else None
        except ValidationError:
            return None
        except Exception:  # noqa: BLE001
            logger.warning("instagram avatar copy failed", exc_info=True)
            return None
