"""IMPORTS routes: upload a file, map its columns, check it, preview, start, cancel, report.

An import writes products AND opening stock into the ledger, so every route needs both
``products:write`` and ``inventory:write`` (the latter is manager/owner, not the frontline role).

The file is the raw request body (the same way product images are uploaded), so no multipart
parser is needed; its name travels in the query string. Nothing here changes the catalog: only
the ``import.run`` job does, after ``start``.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.audit import write_audit_row
from app.core.errors import PayloadTooLargeError, ValidationError
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.imports import service
from app.modules.imports.models import ImportSession
from app.modules.imports.reader import MAX_FILE_BYTES
from app.workers.import_runner import enqueue_import

router = APIRouter(prefix="/imports", tags=["imports"])

_ProductsCtx = Annotated[TenantContext, Depends(require_permission("products:write"))]
_StockCtx = Annotated[TenantContext, Depends(require_permission("inventory:write"))]


def _both(_products: _ProductsCtx, ctx: _StockCtx) -> TenantContext:
    """Both permissions must pass; each dependency resolves the same request's context."""
    return ctx


Ctx = Annotated[TenantContext, Depends(_both)]

_FILENAME_UNSAFE = re.compile(r"[\x00-\x1f\\/:*?\"<>|]+")


class MappingRequest(BaseModel):
    # sheet -> {source column header -> field key, or null to ignore the column}
    mapping: dict[str, dict[str, str | None]] | None = None
    # duplicate_policy: create_only | update | skip   blank_policy: keep | clear
    options: dict[str, str] | None = Field(default=None, max_length=8)


def _clean_filename(raw: str) -> str:
    """A name safe to store and echo: no path, no control characters, bounded length."""
    name = _FILENAME_UNSAFE.sub("_", raw.replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    if not name:
        raise ValidationError("give the file a name (?filename=catalog.xlsx)")
    return name[:255]


def _out(imp: ImportSession) -> dict[str, Any]:
    return {
        "id": str(imp.id),
        "status": imp.status,
        "file_name": imp.file_name,
        "file_size": imp.file_size,
        "options": imp.options,
        "stats": imp.stats,
        "job_id": str(imp.job_id) if imp.job_id else None,
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
    }


async def _audit(ctx: TenantContext, action: str, imp: ImportSession, **after: object) -> None:
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        action=action,
        resource_type="import_session",
        resource_id=str(imp.id),
        after={"file_name": imp.file_name, "status": imp.status, **after},
    )


@router.post("/sessions", status_code=201)
async def upload(
    request: Request, ctx: Ctx, filename: Annotated[str, Query(min_length=1, max_length=255)]
):
    """The raw file is the body. Returns the session and a guess at every sheet's columns."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise PayloadTooLargeError()
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_FILE_BYTES:
            raise PayloadTooLargeError()
    imp = await service.create_session(
        ctx.session,
        ctx.tenant_id,
        file_name=_clean_filename(filename),
        data=bytes(data),
        user_id=ctx.user.id,
    )
    await _audit(ctx, "import.upload", imp, file_size=imp.file_size, sha256=imp.file_sha256)
    return {**_out(imp), **service.describe(imp)}


@router.get("/sessions")
async def list_sessions(ctx: Ctx, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    items = await service.list_sessions(ctx.session, ctx.tenant_id, limit=limit)
    return {"items": [_out(i) for i in items]}


@router.get("/sessions/{session_id}")
async def get_session(session_id: uuid.UUID, ctx: Ctx):
    imp = await service.get(ctx.session, ctx.tenant_id, session_id)
    return {**_out(imp), **service.describe(imp)}


@router.put("/sessions/{session_id}/mapping")
async def set_mapping(session_id: uuid.UUID, body: MappingRequest, ctx: Ctx):
    imp = await service.set_mapping(
        ctx.session, ctx.tenant_id, session_id, mapping=body.mapping, options=body.options
    )
    return {**_out(imp), **service.describe(imp)}


@router.post("/sessions/{session_id}/validate")
async def validate(session_id: uuid.UUID, ctx: Ctx):
    return _out(await service.validate_session(ctx.session, ctx.tenant_id, session_id))


@router.get("/sessions/{session_id}/preview")
async def preview(
    session_id: uuid.UUID, ctx: Ctx, sample: Annotated[int, Query(ge=1, le=100)] = 20
):
    return await service.preview(ctx.session, ctx.tenant_id, session_id, sample=sample)


@router.post("/sessions/{session_id}/start", status_code=202)
async def start(session_id: uuid.UUID, ctx: Ctx):
    imp = await service.start(
        ctx.session, ctx.tenant_id, session_id, user_id=ctx.user.id, enqueue=enqueue_import
    )
    await _audit(ctx, "import.start", imp, to_apply=(imp.stats or {}).get("to_apply"))
    return _out(imp)


@router.post("/sessions/{session_id}/cancel")
async def cancel(session_id: uuid.UUID, ctx: Ctx):
    imp = await service.cancel(ctx.session, ctx.tenant_id, session_id)
    await _audit(ctx, "import.cancel", imp)
    return _out(imp)


def _csv_cell(value: object) -> str:
    """A cell a spreadsheet shows as text and never runs as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/sessions/{session_id}/errors.csv")
async def error_report(session_id: uuid.UUID, ctx: Ctx):
    """Every refused row with its reason. UTF-8 with a BOM so Excel shows Arabic correctly."""
    rows = await service.error_rows(ctx.session, ctx.tenant_id, session_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["sheet", "row", "field", "code", "message", "cells"])
    for r in rows:
        cells = "; ".join(f"{k}={v}" for k, v in r["raw"].items() if v)
        for err in r["errors"] or [{}]:
            writer.writerow(
                [
                    _csv_cell(r["sheet"]),
                    r["row"],
                    _csv_cell(err.get("field")),
                    _csv_cell(err.get("code")),
                    _csv_cell(err.get("message")),
                    _csv_cell(cells),
                ]
            )
    return Response(
        content="\ufeff" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="import-errors.csv"'},
    )
