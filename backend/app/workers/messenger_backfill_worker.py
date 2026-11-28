"""Keep a connected Page's inbox in step with Meta, including what happened before we arrived.

Two jobs share one mechanism:

* **First connect.** A webhook only delivers what happens after the subscription, so a store that
  connects today would open an empty inbox. The first sweep after a connection reads the Page's
  existing threads once.
* **Reconciliation.** A webhook can be missed (a deploy in the middle of a delivery, a lapsed
  subscription, a message Meta sent while the app was down). Every store with a connected Page is
  re-read on a fixed interval so the inbox heals itself instead of staying silently short.

Cost is bounded on purpose: the walk is capped per store, the sweep visits a store only when its
interval has elapsed, and one store's failure never stops the others. Nothing here runs the agent:
the writer stores history as history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.modules.platform.models import Integration

logger = logging.getLogger(__name__)

#: How often a connected Page is re-read. Meta's Conversation API is rate-limited per Page, so this
#: is deliberately hours, not minutes: the webhook is the live path and this is the safety net.
RECONCILE_INTERVAL = timedelta(hours=6)

#: A store that keeps failing must not be retried on every sweep, and must not be abandoned either.
RETRY_INTERVAL = timedelta(hours=1)

#: Caps per store per run. A busy Page is read partially and says so, rather than timing out.
PAGE_SIZE = 25
MAX_CONVERSATIONS = 100
MAX_PAGES = 5


def _last_run(integration: Integration) -> datetime | None:
    metadata = (integration.config or {}).get("_meta") or {}
    backfill = metadata.get("backfill") or {}
    raw = backfill.get("ran_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def is_due(integration: Integration, now: datetime | None = None) -> bool:
    """Has this Page's interval elapsed? A store that never ran is always due."""
    now = now or datetime.now(UTC)
    last = _last_run(integration)
    if last is None:
        return True
    failed = bool(((integration.config or {}).get("_meta") or {}).get("backfill", {}).get("error"))
    return last <= now - (RETRY_INTERVAL if failed else RECONCILE_INTERVAL)


def _record(integration: Integration, summary: dict) -> None:
    """Write the outcome on the integration: when it last ran, and why it stopped."""
    config = dict(integration.config or {})
    metadata = dict(config.get("_meta") or {})
    metadata["backfill"] = {
        "ran_at": datetime.now(UTC).isoformat(),
        "threads": summary.get("threads", 0),
        "messages_stored": summary.get("messages_stored", 0),
        "duplicates": summary.get("duplicates", 0),
        "skipped": summary.get("skipped", 0),
        "stopped": summary.get("stopped"),
        # Kept only when Meta actually failed: an exhausted walk is not an error.
        **({"error": summary["error"]} if summary.get("error") else {}),
    }
    config["_meta"] = metadata
    integration.config = config


async def backfill_one_tenant(tenant_id: uuid.UUID, *, http=None) -> dict | None:
    """Read and store one store's Page history; None when its Messenger is not connected."""
    from app.applications.apparel.modules.conversations.messenger_backfill_service import MessengerBackfillService
    from app.modules.platform.services.channel_access import channel_credentials_config

    async with SessionLocal() as session:
        async with session.begin():
            await bind_tenant(session, tenant_id)
            integration = (
                await session.execute(
                    select(Integration).where(
                        Integration.tenant_id == tenant_id,
                        Integration.provider == "messenger",
                        Integration.kind == "channel",
                        Integration.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if integration is None:
                return None
            credentials = await channel_credentials_config(session, tenant_id, "messenger")
            token = (credentials or {}).get("access_token")
            page_id = str(
                ((integration.config or {}).get("_meta") or {}).get("page_id")
                or (credentials or {}).get("page_id")
                or ((integration.config or {}).get("account_id"))
                or ""
            )
            if not token or not page_id:
                # No Page id or no token: nothing can be asked of Meta, and saying so is the point.
                summary = {"stopped": "error", "error": "no page id or token for this connection"}
                _record(integration, summary)
                return summary

            try:
                summary = await MessengerBackfillService.backfill_tenant(
                    tenant_id,
                    session=session,
                    page_id=page_id,
                    token=token,
                    http=http,
                    page_size=PAGE_SIZE,
                    max_conversations=MAX_CONVERSATIONS,
                    max_pages=MAX_PAGES,
                )
            except Exception as exc:  # noqa: BLE001 - recorded on the row, re-raised to the sweep
                _record(integration, {"stopped": "error", "error": str(exc)[:400]})
                raise
            _record(integration, summary)
            return summary


async def _tenants_with_messenger() -> list[uuid.UUID]:
    from app.modules.identity.models import Tenant

    async with SessionLocal() as session:
        return list(
            (await session.execute(select(Tenant.id).where(Tenant.is_active))).scalars().all()
        )


async def sweep_messenger_backfill(*, http=None, now: datetime | None = None) -> int:
    """Re-read every connected Page whose interval has elapsed. Returns stores read."""
    read = 0
    for tenant_id in await _tenants_with_messenger():
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    integration = (
                        await session.execute(
                            select(Integration).where(
                                Integration.tenant_id == tenant_id,
                                Integration.provider == "messenger",
                                Integration.kind == "channel",
                                Integration.status == "active",
                            )
                        )
                    ).scalar_one_or_none()
            if integration is None or not is_due(integration, now):
                continue
            result = await backfill_one_tenant(tenant_id, http=http)
            if result is not None:
                read += 1
        except Exception:  # noqa: BLE001 - one store must never stop the sweep
            logger.exception("messenger_backfill.failed tenant=%s", tenant_id)
            continue
    return read
