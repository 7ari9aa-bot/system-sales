"""Visitor telemetry recording service — the only writer of visitor_events.

The router parses and validates; this service owns the write (AGENTS rule 2:
routers never write rows). The write is best-effort by contract — the API
returns ``{"ok": False}`` on refusal instead of raising, because a telemetry
write must never break the page that emitted it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.platform.models import VisitorEvent

_EVENT_TYPES = frozenset({"page_view", "click", "error", "performance"})
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def is_valid_event(body: Any) -> bool:
    """The ingest allowlist: unknown event types and malformed ids are refused."""
    if body.event_type not in _EVENT_TYPES:
        return False
    return bool(_ID_RE.match(body.visitor_id)) and bool(_ID_RE.match(body.session_id))


def _ip_hash(ip: str) -> str:
    """SALTED SHA-256 of the visitor IP.

    A bare SHA-256 of an IPv4 address is trivially reversible by enumeration
    (the whole space is ~4 billion); the deployment's JWT secret salts the
    input so the stored hash cannot be brute-forced offline. The column
    docstring and the access-matrix entry both promise "salted".
    """
    salt = get_settings().jwt_secret.encode()
    return hashlib.sha256(salt + ip.encode()).hexdigest()


async def record_visitor_event(
    session: AsyncSession, body: Any, *, ip: str | None, user_agent: str | None
) -> None:
    """Insert one anonymous visitor event.

    Platform-level telemetry: visitor_events has no tenant column and no RLS —
    the IP is stored only as a salted hash, and every free-text field is
    capped so a client cannot use telemetry as a storage bucket.
    """
    metadata = {
        str(key)[:64]: str(value)[:500] for key, value in list((body.metadata or {}).items())[:20]
    }
    await session.execute(
        insert(VisitorEvent).values(
            visitor_id=body.visitor_id,
            session_id=body.session_id,
            event_type=body.event_type,
            path=body.path[:512],
            url=(body.url or "")[:2048] or None,
            referrer=(body.referrer or "")[:2048] or None,
            element=(body.element or "")[:500] or None,
            status_code=body.status_code,
            duration_ms=body.duration_ms,
            metadata_json=metadata,
            user_agent=(user_agent or "")[:1000] or None,
            ip_hash=_ip_hash(ip) if ip else None,
            created_at=datetime.now(UTC),
        )
    )
