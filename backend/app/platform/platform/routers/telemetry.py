"""Public website telemetry — anonymous page/click/error events for the owner console."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.platform.identity.deps import DbSession
from app.platform.platform.services.telemetry import is_valid_event, record_visitor_event

router = APIRouter(prefix="/public", tags=["public"])


class TelemetryEventIn(BaseModel):
    visitor_id: str = Field(min_length=8, max_length=64)
    session_id: str = Field(min_length=8, max_length=64)
    event_type: Literal["page_view", "click", "error", "performance", "rage_click"]
    path: str = Field(min_length=1, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    referrer: str | None = Field(default=None, max_length=2048)
    element: str | None = Field(default=None, max_length=500)
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: int | None = Field(default=None, ge=0, le=600_000)
    metadata: dict = Field(default_factory=dict)


#: Headers the edge sets with the visitor's country. Vercel writes
#: ``x-vercel-ip-country`` on every request it proxies, Cloudflare writes
#: ``cf-ipcountry``; both are ISO-3166 alpha-2.
_COUNTRY_HEADERS = ("x-vercel-ip-country", "cf-ipcountry", "x-country-code")


@router.get("/geo")
async def visitor_country(request: Request) -> dict[str, str | None]:
    """Which country the visitor is in, per the edge — no auth, no database.

    The site uses this to send a visitor to their own market instead of asking
    them to pick one. Unknown is a normal answer: the caller falls back to the
    live market rather than showing a country picker.
    """
    for header in _COUNTRY_HEADERS:
        value = (request.headers.get(header) or "").strip().upper()
        if len(value) == 2 and value.isalpha():
            return {"country": value}
    return {"country": None}


@router.post("/telemetry")
async def ingest_telemetry(
    request: Request,
    session: DbSession,
    body: TelemetryEventIn,
) -> dict[str, bool]:
    """Best-effort, anonymous, no auth — a telemetry write must never break a page."""
    if not is_valid_event(body):
        return {"ok": False}
    ip = request.client.host if request.client else None
    await record_visitor_event(session, body, ip=ip, user_agent=request.headers.get("user-agent"))
    return {"ok": True}
