"""Public website telemetry — anonymous page/click/error events for the owner console."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import insert

from app.modules.identity.deps import DbSession
from app.modules.platform.models import VisitorEvent

router = APIRouter(prefix="/public", tags=["public"])

_EVENT_TYPES = frozenset({"page_view", "click", "error", "performance"})
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class TelemetryEventIn(BaseModel):
    visitor_id: str = Field(min_length=8, max_length=64)
    session_id: str = Field(min_length=8, max_length=64)
    event_type: Literal["page_view", "click", "error", "performance"]
    path: str = Field(min_length=1, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    referrer: str | None = Field(default=None, max_length=2048)
    element: str | None = Field(default=None, max_length=500)
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: int | None = Field(default=None, ge=0, le=600_000)
    metadata: dict = Field(default_factory=dict)


@router.post("/telemetry")
async def ingest_telemetry(
    request: Request,
    session: DbSession,
    body: TelemetryEventIn,
) -> dict[str, bool]:
    """Best-effort, anonymous, no auth — a telemetry write must never break a page."""
    if body.event_type not in _EVENT_TYPES:
        return {"ok": False}
    if not _ID_RE.match(body.visitor_id) or not _ID_RE.match(body.session_id):
        return {"ok": False}
    ip = request.client.host if request.client else None
    ip_hash = hashlib.sha256(ip.encode()).hexdigest() if ip else None
    # Trim metadata so a client cannot use telemetry as a storage bucket.
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
            user_agent=(request.headers.get("user-agent") or "")[:1000] or None,
            ip_hash=ip_hash,
            created_at=datetime.now(UTC),
        )
    )
    return {"ok": True}
