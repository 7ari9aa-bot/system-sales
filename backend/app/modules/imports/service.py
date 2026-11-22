"""The life of one import session: upload, map, check, preview, start, cancel, report.

Everything here is a state change on ``import_sessions`` / ``import_rows`` plus the validators
that already exist. Nothing here writes to the catalog or the ledger: that is ``apply.py``, run
by the ``import.run`` job. So the merchant can upload, remap and re-check as often as they like
and no product changes until they press start.

Order of states::

    uploaded -> analyzed -> mapped -> validated -> running -> completed | failed
                                   \\__ cancelled (until it is running)

Queuing the job needs ``platform``, which this module does not import (the boundary ratchet only
goes down), so ``start`` takes the queuing function from its caller.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import bindparam, func, select, text, update
from sqlalchemy import null as sa_null
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.imports import lookup
from app.modules.imports.apply import BATCH_LIMIT
from app.modules.imports.fields import (
    SHEET_FIELDS,
    SHEET_IMAGES,
    SHEET_ITEM_CODES,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SHEET_VARIANTS,
)
from app.modules.imports.mapping import ignored_columns, missing_required, suggest_mapping
from app.modules.imports.models import ImportRow, ImportSession
from app.modules.imports.reader import SheetData, read_workbook
from app.modules.imports.validation import (
    DUPLICATE_POLICIES,
    RowVerdict,
    summarize,
    validate_images,
    validate_item_codes,
    validate_products,
    validate_stock,
    validate_variants,
)
from app.modules.imports.verdicts import fields_for_row

BLANK_POLICIES = ("keep", "clear")
DEFAULT_OPTIONS = {"duplicate_policy": "create_only", "blank_policy": "keep"}
# Sheets this phase understands. Anything else in the workbook is reported, not guessed at.
KNOWN_SHEETS = (SHEET_PRODUCTS, SHEET_VARIANTS, SHEET_STOCK, SHEET_IMAGES, SHEET_ITEM_CODES)
_EDITABLE = ("uploaded", "analyzed", "mapped", "validated")

_STORE_VERDICTS = text(
    """
    UPDATE import_rows AS r
       SET status = x.status, errors = x.errors,
           parsed = x.parsed,
           updated_at = now()
      FROM jsonb_to_recordset(CAST(:rows AS jsonb))
           AS x(n int, status text, errors jsonb, parsed jsonb)
     WHERE r.session_id = :sid AND r.sheet = :sheet AND r.row_number = x.n
    """
).bindparams(bindparam("rows", type_=JSONB))

EnqueueImport = Callable[[AsyncSession, uuid.UUID, uuid.UUID, uuid.UUID | None], Awaitable[Any]]


def _sheet_key(name: str) -> str | None:
    """Match a sheet to a known one ignoring case and spacing ('opening stock' works)."""
    wanted = " ".join(name.split()).casefold()
    return next((k for k in KNOWN_SHEETS if k.casefold() == wanted), None)


async def get(session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID) -> ImportSession:
    row = (
        await session.execute(
            select(ImportSession).where(
                ImportSession.tenant_id == tenant_id, ImportSession.id == session_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("import session not found")
    return row


async def list_sessions(
    session: AsyncSession, tenant_id: uuid.UUID, *, limit: int = 20
) -> list[ImportSession]:
    rows = await session.execute(
        select(ImportSession)
        .where(ImportSession.tenant_id == tenant_id)
        .order_by(ImportSession.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    return list(rows.scalars())


async def create_session(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    file_name: str,
    data: bytes,
    user_id: uuid.UUID | None,
) -> ImportSession:
    """Read the file (refusing hostile input), keep its rows, and suggest a column mapping.

    The original bytes are not kept: the merchant's price list is private, nothing after this
    point needs it, and every later step reads the rows from the database.
    """
    sheets = read_workbook(file_name, data)
    usable = {_sheet_key(s.name): s for s in sheets if _sheet_key(s.name)}
    if not usable:
        # A CSV is one sheet of unknown name: it can only be the product list.
        if len(sheets) == 1 and file_name.lower().endswith((".csv", ".txt")):
            usable = {SHEET_PRODUCTS: sheets[0]}
        else:
            raise ValidationError(
                "no sheet named Products, Variants or Opening Stock was found in the file"
            )
    ignored = sorted(s.name for s in sheets if _sheet_key(s.name) is None and usable)

    imp = ImportSession(
        tenant_id=tenant_id,
        kind="products",
        status="analyzed",
        file_name=file_name[:255],
        file_size=len(data),
        file_sha256=hashlib.sha256(data).hexdigest(),
        options=dict(DEFAULT_OPTIONS),
        created_by=user_id,
    )
    mapping: dict[str, dict[str, str | None]] = {}
    counts: dict[str, int] = {}
    session.add(imp)
    await session.flush()
    for key, sheet in usable.items():
        mapping[key] = suggest_mapping(key, sheet.headers)
        counts[key] = len(sheet.rows)
        session.add_all(
            ImportRow(
                tenant_id=tenant_id,
                session_id=imp.id,
                sheet=key,
                row_number=i + 2,
                raw=row,
                status="pending",
            )
            for i, row in enumerate(sheet.rows)
        )
    imp.mapping = mapping
    imp.stats = {"rows": counts, "ignored_sheets": ignored}
    await session.flush()
    return imp


async def create_session_from_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    sheets: dict[str, list[dict[str, str]]],
    user_id: uuid.UUID | None,
    file_name: str = "لصق من Excel",
) -> ImportSession:
    """A session built from rows the merchant pasted, not from a file.

    Same shape as an upload: the rows are stored, the columns are guessed from their headers, and
    everything after this point (mapping, validation, apply) cannot tell the two apart.
    """
    if not sheets:
        raise ValidationError("لا يوجد صفوف في اللصق")

    imp = ImportSession(
        tenant_id=tenant_id,
        kind="products",
        status="analyzed",
        file_name=file_name[:255],
        file_size=0,
        file_sha256=None,
        options=dict(DEFAULT_OPTIONS),
        created_by=user_id,
    )
    mapping: dict[str, dict[str, str | None]] = {}
    counts: dict[str, int] = {}
    session.add(imp)
    await session.flush()
    for key, rows in sheets.items():
        if not rows:
            continue
        headers = list(rows[0].keys())
        mapping[key] = suggest_mapping(key, headers)
        counts[key] = len(rows)
        session.add_all(
            ImportRow(
                tenant_id=tenant_id,
                session_id=imp.id,
                sheet=key,
                row_number=i + 2,
                raw=row,
                status="pending",
            )
            for i, row in enumerate(rows)
        )
    if not mapping:
        raise ValidationError("لا يوجد صفوف في اللصق")
    imp.mapping = mapping
    imp.stats = {"rows": counts, "ignored_sheets": [], "pasted": True}
    await session.flush()
    return imp


def describe(imp: ImportSession) -> dict[str, Any]:
    """What the mapping screen needs: each sheet, its columns, the guess, and what is missing."""
    sheets = {}
    for sheet, mapping in (imp.mapping or {}).items():
        sheets[sheet] = {
            "rows": (imp.stats or {}).get("rows", {}).get(sheet, 0),
            "mapping": mapping,
            "missing_required": missing_required(sheet, mapping),
            "ignored_columns": ignored_columns(sheet, mapping),
            "fields": [
                {
                    "key": f.key,
                    "label_ar": f.label_ar,
                    "label_en": f.label_en,
                    "required": f.required,
                }
                for f in SHEET_FIELDS.get(sheet, ())
            ],
        }
    return {"sheets": sheets, "options": imp.options}


async def set_mapping(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    mapping: dict[str, dict[str, str | None]] | None,
    options: dict[str, str] | None,
) -> ImportSession:
    imp = await get(session, tenant_id, session_id)
    if imp.status not in _EDITABLE:
        raise ConflictError(f"the import is {imp.status}; it can no longer be changed")

    new_mapping = {s: dict(m) for s, m in (imp.mapping or {}).items()}
    for sheet, chosen in (mapping or {}).items():
        if sheet not in new_mapping:
            raise ValidationError(f"the file has no sheet '{sheet}'")
        valid_fields = {f.key for f in SHEET_FIELDS.get(sheet, ())}
        for header, field_key in chosen.items():
            if header not in new_mapping[sheet]:
                raise ValidationError(f"sheet '{sheet}' has no column '{header}'")
            if field_key is not None and field_key not in valid_fields:
                raise ValidationError(f"'{field_key}' is not a field of sheet '{sheet}'")
        targets = [v for v in chosen.values() if v]
        if len(targets) != len(set(targets)):
            raise ValidationError(f"two columns of '{sheet}' are mapped to the same field")
        new_mapping[sheet].update(chosen)

    new_options = {**DEFAULT_OPTIONS, **(imp.options or {})}
    for name, value in (options or {}).items():
        allowed = {"duplicate_policy": DUPLICATE_POLICIES, "blank_policy": BLANK_POLICIES}.get(name)
        if allowed is None or value not in allowed:
            raise ValidationError(f"invalid option {name}={value!r}")
        new_options[name] = value

    imp.mapping = new_mapping
    imp.options = new_options
    # Any change makes an earlier check stale: the merchant must check again before starting.
    imp.status = "mapped"
    imp.stats = {k: v for k, v in (imp.stats or {}).items() if k in ("rows", "ignored_sheets")}
    await session.execute(
        update(ImportRow)
        .where(ImportRow.session_id == imp.id)
        .values(status="pending", errors=[], parsed=sa_null())
    )
    await session.flush()
    return imp


async def _rows_of(session: AsyncSession, session_id: uuid.UUID, sheet: str):
    """A sheet's rows in file order, ``(row_number, raw)``; read in one pass per sheet."""
    result = await session.execute(
        select(ImportRow.row_number, ImportRow.raw)
        .where(ImportRow.session_id == session_id, ImportRow.sheet == sheet)
        .order_by(ImportRow.row_number)
    )
    return [(n, dict(raw)) for n, raw in result.all()]


def _collect(rows, mapping, field_key) -> set[str]:
    header = next((h for h, f in mapping.items() if f == field_key), None)
    return {v.strip() for _, r in rows if header and (v := r.get(header)) and v.strip()}


async def validate_session(
    session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> ImportSession:
    """Check every row against the file and the shop, store each verdict, count the result."""
    from app.modules.imports.normalize import slugify

    imp = await get(session, tenant_id, session_id)
    if imp.status not in _EDITABLE:
        raise ConflictError(f"the import is {imp.status}; it can no longer be checked")
    problems = {s: missing_required(s, m) for s, m in imp.mapping.items()}
    problems = {s: miss for s, miss in problems.items() if miss}
    if problems:
        detail = "; ".join(f"{s}: {', '.join(m)}" for s, m in problems.items())
        raise ValidationError(f"map the required columns first ({detail})")

    policy = (imp.options or {}).get("duplicate_policy", "create_only")
    rows = {s: await _rows_of(session, imp.id, s) for s in imp.mapping}
    maps = imp.mapping

    product_rows = rows.get(SHEET_PRODUCTS, [])
    variant_rows = rows.get(SHEET_VARIANTS, [])
    stock_rows = rows.get(SHEET_STOCK, [])
    refs = {slugify(r) for r in _collect(product_rows, maps.get(SHEET_PRODUCTS, {}), "product_ref")}
    refs |= {slugify(t) for t in _collect(product_rows, maps.get(SHEET_PRODUCTS, {}), "title")}
    refs |= {
        slugify(r) for r in _collect(variant_rows, maps.get(SHEET_VARIANTS, {}), "product_ref")
    }
    skus = _collect(variant_rows, maps.get(SHEET_VARIANTS, {}), "sku")
    stock_skus = _collect(stock_rows, maps.get(SHEET_STOCK, {}), "sku")
    image_rows = rows.get(SHEET_IMAGES, [])
    image_skus = _collect(image_rows, maps.get(SHEET_IMAGES, {}), "sku")
    code_rows = rows.get(SHEET_ITEM_CODES, [])
    code_skus = _collect(code_rows, maps.get(SHEET_ITEM_CODES, {}), "sku")
    barcodes = _collect(variant_rows, maps.get(SHEET_VARIANTS, {}), "barcode")

    existing = await lookup.load_existing(
        session,
        tenant_id,
        product_refs=refs,
        skus=skus | stock_skus | image_skus | code_skus,
        barcodes=barcodes,
    )
    existing.opening_stock_done = await lookup.load_opening_stock_done(
        session, tenant_id, stock_skus
    )
    known = await lookup.known_variant_skus(session, tenant_id, stock_skus | image_skus | code_skus)
    attached = await lookup.load_attached_images(session, tenant_id, image_skus)

    verdicts: dict[str, list[RowVerdict]] = {}
    if SHEET_PRODUCTS in maps:
        verdicts[SHEET_PRODUCTS] = validate_products(
            product_rows, maps[SHEET_PRODUCTS], existing, duplicate_policy=policy
        )
    file_refs = {v.values["product_ref"] for v in verdicts.get(SHEET_PRODUCTS, []) if v.ok}
    if SHEET_VARIANTS in maps:
        verdicts[SHEET_VARIANTS] = validate_variants(
            variant_rows,
            maps[SHEET_VARIANTS],
            existing,
            product_refs_in_file=file_refs,
            duplicate_policy=policy,
        )
    file_skus = {
        v.values["sku"] for v in verdicts.get(SHEET_VARIANTS, []) if v.ok and v.values.get("sku")
    }
    if SHEET_STOCK in maps:
        verdicts[SHEET_STOCK] = validate_stock(
            stock_rows,
            maps[SHEET_STOCK],
            existing,
            skus_in_file=file_skus,
            known_skus=known,
            default_warehouse=lookup.default_warehouse(existing, None),
        )
    if SHEET_IMAGES in maps:
        verdicts[SHEET_IMAGES] = validate_images(
            image_rows,
            maps[SHEET_IMAGES],
            skus_in_file=file_skus,
            known_skus=known,
            already_attached=attached,
        )

    if SHEET_ITEM_CODES in maps:
        verdicts[SHEET_ITEM_CODES] = validate_item_codes(
            code_rows,
            maps[SHEET_ITEM_CODES],
            skus_in_file=file_skus,
            known_skus=known,
            existing=await lookup.load_item_code_owners(
                session, tenant_id, _collect(code_rows, maps[SHEET_ITEM_CODES], "code")
            ),
            held_by_sku=await lookup.load_codes_by_sku(session, tenant_id, code_skus),
        )

    # One UPDATE per 500 rows, not one per row: a full file is 100k rows. The chunk travels as
    # a single JSON array that the statement unpacks, so the values are bound, never formatted in.
    by_sheet_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sheet, items in verdicts.items():
        for start in range(0, len(items), BATCH_LIMIT):
            chunk = []
            for v in items[start : start + BATCH_LIMIT]:
                fields = fields_for_row(v)
                by_sheet_status[sheet][fields["status"]] += 1
                chunk.append({"n": v.row_number, **fields})
            await session.execute(_STORE_VERDICTS, {"sid": imp.id, "sheet": sheet, "rows": chunk})
    imp.stats = {
        **{k: v for k, v in (imp.stats or {}).items() if k in ("rows", "ignored_sheets")},
        "sheets": {s: summarize(v) for s, v in verdicts.items()},
        "by_status": {s: dict(c) for s, c in by_sheet_status.items()},
    }
    imp.status = "validated"
    await session.flush()
    return imp


async def preview(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    sample: int = 20,
) -> dict[str, Any]:
    """The counters plus the first rows that would not import, so the merchant can fix them."""
    imp = await get(session, tenant_id, session_id)
    bad = await session.execute(
        select(ImportRow.sheet, ImportRow.row_number, ImportRow.errors)
        .where(ImportRow.session_id == imp.id, ImportRow.status == "error")
        .order_by(ImportRow.sheet, ImportRow.row_number)
        .limit(max(1, min(sample, 100)))
    )
    return {
        "status": imp.status,
        "stats": imp.stats,
        "sample_errors": [{"sheet": s, "row": n, "errors": e} for s, n, e in bad.all()],
    }


async def start(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
    enqueue: EnqueueImport,
) -> ImportSession:
    """Queue the first ``import.run`` job. Only a checked import with something to apply starts."""
    imp = (
        await session.execute(
            select(ImportSession)
            .where(ImportSession.tenant_id == tenant_id, ImportSession.id == session_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if imp is None:
        raise NotFoundError("import session not found")
    if imp.status == "running":
        raise ConflictError("this import is already running")
    if imp.status != "validated":
        raise ConflictError("check the file before starting the import")
    valid = (
        await session.execute(
            select(func.count())
            .select_from(ImportRow)
            .where(ImportRow.session_id == imp.id, ImportRow.status == "valid")
        )
    ).scalar_one()
    if valid == 0:
        raise ValidationError("no row can be imported; fix the errors and check again")
    job = await enqueue(session, tenant_id, imp.id, user_id)
    imp.job_id = job.id
    imp.status = "running"
    imp.stats = {**(imp.stats or {}), "to_apply": valid}
    await session.flush()
    return imp


async def cancel(
    session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> ImportSession:
    """Stop an import. Rows already applied stay applied; the rest are never taken."""
    imp = await get(session, tenant_id, session_id)
    if imp.status in ("completed", "failed", "cancelled"):
        raise ConflictError(f"the import is already {imp.status}")
    imp.status = "cancelled"
    await session.flush()
    return imp


async def error_rows(
    session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every row that did not import, with the reason, for the downloadable report."""
    imp = await get(session, tenant_id, session_id)
    result = await session.execute(
        select(ImportRow.sheet, ImportRow.row_number, ImportRow.raw, ImportRow.errors)
        .where(ImportRow.session_id == imp.id, ImportRow.status == "error")
        .order_by(ImportRow.sheet, ImportRow.row_number)
    )
    return [{"sheet": s, "row": n, "raw": raw, "errors": errs} for s, n, raw, errs in result.all()]


__all__ = [
    "SheetData",
    "cancel",
    "create_session",
    "describe",
    "error_rows",
    "get",
    "list_sessions",
    "preview",
    "set_mapping",
    "start",
    "validate_session",
]
