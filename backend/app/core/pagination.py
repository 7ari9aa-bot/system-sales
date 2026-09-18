"""Cursor (keyset) pagination helpers.

Cursors are opaque URL-safe base64 strings encoding the last row's
``(created_at, id)`` position. Lists are keyset-paginated with
``WHERE (created_at, id) < (:cursor) ORDER BY created_at DESC, id DESC`` —
stable under concurrent inserts and far cheaper than OFFSET on large tables.

Any model with ``created_at`` + ``id`` columns works (multi-tenant tables all
carry both).
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.errors import InvalidCursorError

_KEY_CREATED_AT = "created_at"
_KEY_ID = "id"


def encode_cursor(created_at: datetime, id: UUID | str) -> str:
    """Encode a row position as an opaque, URL-safe cursor string."""
    payload = json.dumps(
        {_KEY_CREATED_AT: created_at.isoformat(), _KEY_ID: str(id)},
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Decode a cursor back to ``(created_at, id)``.

    Malformed cursors (bad base64, bad JSON, missing fields, non-UUID id)
    raise :class:`InvalidCursorError` (a ``ValidationError`` with code
    ``invalid_cursor``).
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        created_at = datetime.fromisoformat(str(payload[_KEY_CREATED_AT]))
        row_id = UUID(str(payload[_KEY_ID]))
    except (binascii.Error, UnicodeDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InvalidCursorError(details={"cursor": cursor[:128]}) from exc
    return created_at, row_id


def page_slice(items: Sequence[Any], limit: int) -> tuple[list[Any], str | None]:
    """Split a ``limit + 1`` fetch into ``(page, next_cursor)``.

    ``items`` must be ordered so pagination advances toward its last element
    (descending lists: newest first). When more rows exist beyond ``limit``,
    the cursor points at the last row OF THE PAGE; otherwise it is ``None``.
    """
    if len(items) <= limit:
        return list(items), None
    page = list(items[:limit])
    last = page[-1]
    return page, encode_cursor(last.created_at, last.id)


async def paginate(
    session: AsyncSession,
    stmt: Select,
    *,
    cursor: str | None = None,
    limit: int = 50,
    order_desc: bool = True,
) -> tuple[list[Any], str | None]:
    """Keyset-paginate a ``select(Model)`` statement.

    Applies ``WHERE (created_at, id) < (:cursor)`` (``>`` when ascending),
    ``ORDER BY created_at DESC, id DESC`` and ``LIMIT limit + 1``; returns
    ``(items, next_cursor | None)``. The model is taken from the statement's
    first entity and must expose ``created_at`` and ``id`` columns.
    """
    entity = stmt.column_descriptions[0]["entity"]
    if entity is None:  # pragma: no cover — caller passed a column select
        raise ValueError("paginate() needs select(Model) with created_at + id columns")
    created_at_col = entity.created_at
    id_col = entity.id

    if cursor is not None:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        cursor_tuple = tuple_(cursor_created_at, cursor_id)
        stmt = stmt.where(
            tuple_(created_at_col, id_col) < cursor_tuple
            if order_desc
            else tuple_(created_at_col, id_col) > cursor_tuple
        )
    order = (created_at_col.desc(), id_col.desc()) if order_desc else (
        created_at_col.asc(),
        id_col.asc(),
    )
    stmt = stmt.order_by(*order).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    return page_slice(rows, limit)
