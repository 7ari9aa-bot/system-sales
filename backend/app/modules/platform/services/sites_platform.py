"""Narrow client for the Fihrist Sites platform database (owner console "Websites").

Fihrist Sites is a separate product with its own Supabase project. The owner
console here manages it, so the backend calls that project's PostgREST API with
a service-role key. That key opens every merchant's data, so this module is
deliberately NOT a general gateway:

* it can only touch the tables and columns listed in ``_READ`` / ``_WRITE``;
* it never deletes (destructive operations stay in the platform's own console,
  behind its typed confirmations);
* every id is validated as a UUID and every value is URL-encoded before it
  reaches a filter, so a crafted string cannot add or change a PostgREST filter;
* redirects are off and the timeout is short, so a misconfigured URL cannot be
  turned into a request elsewhere;
* the key is never logged and never appears in an error message.

When the two settings are empty (the default) every call raises
``SitesPlatformNotConfigured`` and the router answers 503, so shipping this code
changes nothing until the owner supplies the key.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_ROWS = 500

# Columns the console may READ, per table.
# Customer personal data (names, phones, addresses) is never listed.
_READ: dict[str, tuple[str, ...]] = {
    "sites": ("id", "slug", "name", "design", "status", "created_at"),
    "designs": (
        "key",
        "name",
        "is_live",
        "is_listed",
        "price_egp",
        "sort_order",
        "tagline",
        "category",
    ),
    "purchase_orders": (
        "id",
        "user_id",
        "design",
        "slug",
        "site_name",
        "amount_egp",
        "status",
        "payment_ref",
        "site_id",
        "created_at",
        "confirmed_at",
    ),
    "platform_limits": ("key", "value", "label"),
    "platform_legal": (
        "slug",
        "title",
        "summary",
        "sections",
        "is_draft",
        "sort_order",
        "updated_at",
        "owner_edited_at",
        "published_at",
    ),
    "fihrist_links": (
        "site_id",
        "key_hint",
        "linked_at",
        "last_sync_at",
        "last_sync_status",
        "last_sync_error",
        "last_sync_count",
        "sync_enabled",
    ),
    "owner_audit": ("id", "actor", "action", "target", "detail", "created_at"),
    "contact_messages": ("id", "site_id", "project_type", "created_at", "read_at"),
    "products": ("id", "site_id", "source"),
    "orders": ("id", "site_id", "status", "total"),
    "coupons": ("id", "site_id", "is_active"),
    "page_stats": ("site_id", "day", "views"),
}

# Columns the console may CHANGE, per table. Everything else is read-only here.
_WRITE: dict[str, frozenset[str]] = {
    "designs": frozenset({"is_listed", "price_egp"}),
    "platform_limits": frozenset({"value"}),
    "platform_legal": frozenset(
        {
            "title",
            "summary",
            "sections",
            "is_draft",
            "updated_at",
            "owner_edited_at",
            "published_at",
        }
    ),
    "fihrist_links": frozenset({"sync_enabled"}),
    "sites": frozenset({"status"}),
}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# A value for neq/gte: a date or a short word (status names are Arabic, so letters of any script),
# never anything with a comma, parenthesis, dot-operator or space that could start another filter.
_FILTER_VALUE = re.compile(r"^[\w\u0600-\u06FF-]{1,40}$")


class SitesPlatformNotConfigured(RuntimeError):
    """The two settings are empty: the section is installed but switched off."""


class SitesPlatformError(RuntimeError):
    """The platform answered with an error. The message is safe to show."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_configured() -> bool:
    s = get_settings()
    return bool(s.sites_platform_supabase_url and s.sites_platform_service_key)


def uuid_or_none(value: object) -> str | None:
    """A canonical lowercase UUID string, or None. The only id shape allowed in a filter."""
    try:
        return str(uuid.UUID(str(value))) if _UUID.match(str(value).lower()) else None
    except ValueError:
        return None


def key_or_none(value: object) -> str | None:
    """A short slug-like key (design key, limit key, legal slug), or None."""
    v = str(value)
    return v if _KEY.match(v) else None


def _in_item(value: object) -> str:
    """One item of a PostgREST ``in.(...)`` list: double-quoted so ``,`` ``(`` ``)`` stay data."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _base() -> tuple[str, dict[str, str]]:
    s = get_settings()
    if not (s.sites_platform_supabase_url and s.sites_platform_service_key):
        raise SitesPlatformNotConfigured("Fihrist Sites platform is not configured")
    url = s.sites_platform_supabase_url.rstrip("/")
    if not url.startswith("https://"):
        raise SitesPlatformNotConfigured("Fihrist Sites platform URL must be https")
    key = s.sites_platform_service_key
    return f"{url}/rest/v1", {
        "apikey": key,
        "authorization": f"Bearer {key}",
        "content-type": "application/json",
        "accept": "application/json",
    }


def _fail(resp: httpx.Response, what: str) -> SitesPlatformError:
    # Never echo the body: PostgREST errors can name internal columns.
    log.warning("sites-platform %s failed with HTTP %s", what, resp.status_code)
    return SitesPlatformError(
        f"Fihrist Sites platform rejected the request ({resp.status_code})", 502
    )


async def select(
    table: str,
    *,
    eq: dict[str, str] | None = None,
    in_: tuple[str, list[str]] | None = None,
    neq: dict[str, str] | None = None,
    gte: dict[str, str] | None = None,
    order: str | None = None,
    limit: int = 100,
    count_only: bool = False,
) -> Any:
    """Read rows. ``eq`` values must be UUIDs or short keys (see uuid_or_none).

    ``neq`` (not equal) and ``gte`` (on or after) are for the per-site activity numbers: a status
    to leave out, a day to start from. Both go through the same column allow-list and the same
    value check as ``eq``, so neither can smuggle in a second filter.
    """
    cols = _READ.get(table)
    if cols is None:
        raise SitesPlatformError(f"table not readable: {table}", 400)
    base, headers = _base()
    params: list[tuple[str, str]] = [
        ("select", "id" if count_only and "id" in cols else ",".join(cols))
    ]
    for col, val in (eq or {}).items():
        if col not in cols:
            raise SitesPlatformError(f"column not filterable: {col}", 400)
        params.append((col, "eq." + str(val)))
    for op, group in (("neq", neq), ("gte", gte)):
        for col, val in (group or {}).items():
            if col not in cols:
                raise SitesPlatformError(f"column not filterable: {col}", 400)
            if not _FILTER_VALUE.match(str(val)):
                raise SitesPlatformError(f"value not allowed in a filter: {col}", 400)
            params.append((col, f"{op}.{val}"))
    if in_:
        col, vals = in_
        if col not in cols:
            raise SitesPlatformError(f"column not filterable: {col}", 400)
        if vals:
            params.append((col, "in.(" + ",".join(_in_item(v) for v in vals[:_MAX_ROWS]) + ")"))
    if order:
        col = order.lstrip("-")
        if col not in cols:
            raise SitesPlatformError(f"column not sortable: {col}", 400)
        params.append(("order", f"{col}.{'desc' if order.startswith('-') else 'asc'}"))
    params.append(("limit", str(max(1, min(int(limit), _MAX_ROWS)))))
    if count_only:
        headers = {**headers, "prefer": "count=exact", "range-unit": "items"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        try:
            resp = await client.get(f"{base}/{table}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("sites-platform select %s unreachable: %s", table, type(exc).__name__)
            raise SitesPlatformError("Fihrist Sites platform is unreachable", 502) from exc
    if resp.status_code >= 400:
        raise _fail(resp, f"select {table}")
    if count_only:
        total = resp.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else 0
    return resp.json()


async def update(table: str, match: dict[str, str], values: dict[str, Any]) -> int:
    """Change allow-listed columns on matched rows. Returns the row count. Never deletes."""
    allowed = _WRITE.get(table)
    if allowed is None:
        raise SitesPlatformError(f"table not writable: {table}", 400)
    bad = set(values) - allowed
    if bad or not values:
        raise SitesPlatformError("column not writable", 400)
    if not match:
        raise SitesPlatformError("refusing an update with no filter", 400)
    base, headers = _base()
    params = []
    for col, val in match.items():
        if col not in _READ[table]:
            raise SitesPlatformError(f"column not filterable: {col}", 400)
        params.append((col, "eq." + str(val)))
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        try:
            resp = await client.patch(
                f"{base}/{table}",
                params=params,
                json=values,
                headers={**headers, "prefer": "return=representation"},
            )
        except httpx.HTTPError as exc:
            log.warning("sites-platform update %s unreachable: %s", table, type(exc).__name__)
            raise SitesPlatformError("Fihrist Sites platform is unreachable", 502) from exc
    if resp.status_code >= 400:
        raise _fail(resp, f"update {table}")
    return len(resp.json())
