"""Read a merchant's spreadsheet into plain rows, safely.

The file is untrusted input. Limits are enforced WHILE reading (never "read it all, then
check"), macro workbooks are refused, and a formula is returned as its cached value, never as
something to evaluate. Pure functions over bytes: no database, no network.

Excel is read with ``openpyxl`` in ``read_only`` mode, which streams rows instead of building
the whole workbook in memory; that is what lets a 100k-row file be read by a small worker.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.errors import ValidationError

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 60
MAX_CELL_CHARS = 2000
MAX_SHEETS = 12
# An .xlsx is a zip: refuse one that inflates to far more than it claims (zip bomb).
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

_XLSX_MAGIC = b"PK\x03\x04"
_MACRO_PARTS = ("xl/vbaProject.bin",)


@dataclass(slots=True)
class SheetData:
    name: str
    headers: list[str]
    rows: list[dict[str, str]]  # keyed by header; row index is position + 2 (header is row 1)


def _clean(value: object) -> str:
    """One cell as trimmed text. Numbers that are whole print without a trailing ``.0``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) > MAX_CELL_CHARS:
        raise ValidationError(f"a cell is longer than {MAX_CELL_CHARS} characters")
    return text


def sniff_format(filename: str, data: bytes) -> str:
    """``xlsx`` or ``csv``. Macro workbooks and the legacy ``.xls`` are refused by name."""
    name = (filename or "").lower()
    if name.endswith((".xlsm", ".xlsb", ".xls")):
        raise ValidationError("save the file as .xlsx or .csv and upload it again")
    if data[:4] == _XLSX_MAGIC:
        return "xlsx"
    if name.endswith(".xlsx"):
        raise ValidationError("this file is not a valid .xlsx workbook")
    return "csv"


def _guard_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if any(part in names for part in _MACRO_PARTS):
                raise ValidationError("workbooks with macros are not accepted")
            if sum(info.file_size for info in zf.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ValidationError("the workbook is too large once unpacked")
    except zipfile.BadZipFile as exc:
        raise ValidationError("this file is not a valid .xlsx workbook") from exc


def _decode_csv(data: bytes) -> str:
    """UTF-8 (with or without BOM) first, then Windows Arabic (cp1256, Excel's default there)."""
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError("could not read the file encoding; save it as UTF-8 CSV")


def _dedupe_headers(raw: list[str]) -> list[str]:
    """Blank headers get a stable placeholder; repeated ones get a numeric suffix."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, h in enumerate(raw, start=1):
        base = h or f"column_{i}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n + 1}")
    return out


def _build(name: str, raw_rows: Iterator[list[str]]) -> SheetData:
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    for cells in raw_rows:
        if headers is None:
            if not any(cells):
                continue  # leading blank lines before the header
            trimmed = list(cells)
            while trimmed and not trimmed[-1]:
                trimmed.pop()
            if len(trimmed) > MAX_COLUMNS:
                raise ValidationError(f"more than {MAX_COLUMNS} columns")
            headers = _dedupe_headers(trimmed)
            continue
        if not any(cells):
            continue  # fully blank row
        if len(rows) >= MAX_ROWS:
            raise ValidationError(f"more than {MAX_ROWS} rows; split the file")
        padded = list(cells[: len(headers)]) + [""] * max(0, len(headers) - len(cells))
        rows.append(dict(zip(headers, padded, strict=True)))
    return SheetData(name=name, headers=headers or [], rows=rows)


def read_csv(data: bytes, name: str = "Sheet1") -> list[SheetData]:
    text = _decode_csv(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    return [_build(name, ([_clean(c) for c in line] for line in reader))]


def read_xlsx(data: bytes) -> list[SheetData]:
    _guard_zip(data)
    from openpyxl import load_workbook  # imported here: only the Excel path needs it

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for a corrupt file
        raise ValidationError("this file is not a valid .xlsx workbook") from exc
    try:
        if len(wb.sheetnames) > MAX_SHEETS:
            raise ValidationError(f"more than {MAX_SHEETS} sheets")
        sheets = []
        for ws in wb.worksheets:
            sheets.append(
                _build(
                    ws.title,
                    ([_clean(c) for c in row] for row in ws.iter_rows(values_only=True)),
                )
            )
        return sheets
    finally:
        wb.close()


def read_workbook(filename: str, data: bytes) -> list[SheetData]:
    """Every sheet of the file (a CSV is one sheet), refusing oversize or hostile input."""
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError(f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    if not data:
        raise ValidationError("the file is empty")
    return read_xlsx(data) if sniff_format(filename, data) == "xlsx" else read_csv(data)
