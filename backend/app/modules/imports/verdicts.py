"""Store a validator verdict on its row, and read it back.

The preview and the run must agree, so the run applies the verdict the preview showed instead of
parsing ``raw`` again with whatever the parser has become since. JSON has no Decimal, so money and
quantities travel as strings and come back as ``Decimal`` without passing through a float.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.imports.models import ImportRow
from app.modules.imports.validation import RowVerdict

_DECIMAL_FIELDS = frozenset({"price", "cost", "quantity"})


def encode_values(values: dict[str, object]) -> dict[str, object]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in values.items()}


def decode_values(values: dict[str, object]) -> dict[str, object]:
    return {
        k: (Decimal(str(v)) if k in _DECIMAL_FIELDS and v is not None else v)
        for k, v in values.items()
    }


def status_of(verdict: RowVerdict) -> str:
    """``valid`` rows get applied; ``skip`` rows are settled now and never reach the run."""
    if not verdict.ok:
        return "error"
    return "skipped" if verdict.action == "skip" else "valid"


def fields_for_row(verdict: RowVerdict) -> dict[str, object]:
    """The columns of ``import_rows`` that a verdict decides."""
    return {
        "status": status_of(verdict),
        "errors": [e.as_dict() for e in verdict.errors],
        "parsed": (
            {"action": verdict.action, "values": encode_values(verdict.values)}
            if verdict.ok
            else None
        ),
    }


def values_of(row: ImportRow) -> tuple[str, dict[str, object]]:
    """``(action, clean values)`` of a stored row, ready for ``apply_batch``."""
    parsed = row.parsed or {}
    return str(parsed.get("action") or "create"), decode_values(dict(parsed.get("values") or {}))
