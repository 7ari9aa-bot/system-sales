"""Judge every row of an import before anything is written.

Pure and database-free. The caller hands in the mapped rows of each sheet and, separately, what
the catalog already holds (``Existing``); the result says, per row, whether it is valid and what
it would do (create or update). Nothing here writes, so the same function drives the preview
and the run, and the two cannot disagree.

Identity follows the rule in the module README: SKU, then barcode. A name alone never decides
that two rows are the same thing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.modules.imports import normalize as n
from app.modules.imports.fields import (
    SHEET_IMAGES,
    SHEET_ITEM_CODES,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SHEET_VARIANTS,
)
from app.modules.imports.normalize import CellError

DUPLICATE_POLICIES = ("create_only", "update", "skip")


@dataclass(frozen=True, slots=True)
class RowError:
    field: str | None
    code: str
    message: str

    def as_dict(self) -> dict[str, str | None]:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass(slots=True)
class Existing:
    """What the catalog already holds for this tenant, restricted to the keys in the file."""

    product_slugs: set[str] = field(default_factory=set)
    # sku -> slug of the product that owns it
    sku_owner: dict[str, str] = field(default_factory=dict)
    # barcode value -> sku of the variant that owns it
    barcode_owner: dict[str, str] = field(default_factory=dict)
    warehouse_codes: set[str] = field(default_factory=set)
    # (sku, warehouse code) pairs that already have an opening-stock movement
    opening_stock_done: set[tuple[str, str]] = field(default_factory=set)


@dataclass(slots=True)
class RowVerdict:
    sheet: str
    row_number: int
    errors: list[RowError] = field(default_factory=list)
    action: str | None = None  # create | update | skip, set when the row is valid
    values: dict[str, object] = field(default_factory=dict)  # the parsed, clean values

    @property
    def ok(self) -> bool:
        return not self.errors


def _get(row: dict[str, str], mapping: dict[str, str | None], key: str) -> str:
    """The cell mapped to field ``key`` ('' when no column is mapped to it)."""
    for header, mapped in mapping.items():
        if mapped == key:
            return row.get(header, "")
    return ""


def _try(verdict: RowVerdict, field_key: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except CellError as exc:
        verdict.errors.append(RowError(field_key, exc.code, exc.message))
        return None


def validate_products(
    rows: list[tuple[int, dict[str, str]]],
    mapping: dict[str, str | None],
    existing: Existing,
    *,
    duplicate_policy: str,
) -> list[RowVerdict]:
    """The Products sheet: one row per product, keyed by ``product_ref``."""
    verdicts: list[RowVerdict] = []
    first_seen: dict[str, int] = {}
    for number, row in rows:
        v = RowVerdict(SHEET_PRODUCTS, number)
        ref = _try(
            v,
            "product_ref",
            _product_ref,
            _get(row, mapping, "product_ref"),
            _get(row, mapping, "title"),
        )
        title = _try(v, "title", n.parse_title, _get(row, mapping, "title"), field="title")
        status = _try(v, "status", n.parse_status, _get(row, mapping, "status"))
        if ref is not None:
            if ref in first_seen:
                v.errors.append(
                    RowError("product_ref", "duplicate_in_file", f"same as row {first_seen[ref]}")
                )
            else:
                first_seen[ref] = number
        if v.ok:
            v.values = {
                "product_ref": ref,
                "title": title,
                "status": status,
                "category": n.clean_text(_get(row, mapping, "category")) or None,
                "brand": n.clean_text(_get(row, mapping, "brand")) or None,
                "description": n.clean_text(_get(row, mapping, "description")) or None,
            }
            v.action = _action(ref in existing.product_slugs, duplicate_policy)
        verdicts.append(v)
    return verdicts


def _product_ref(raw: str, title_raw: str) -> str:
    """The merchant's own key for the product; falls back to a slug of the name only when absent.

    The fallback keeps a simple one-sheet file working, but it is the name that decides identity
    there, so ``validate_products`` still refuses two rows that resolve to the same handle.
    """
    ref = n.slugify(raw) if n.clean_text(raw) else n.slugify(title_raw)
    if not ref:
        raise CellError("required", "product_ref is required")
    return ref


def _action(exists: bool, policy: str) -> str:
    if not exists:
        return "create"
    return {"update": "update", "skip": "skip"}.get(policy, "skip")


def validate_variants(
    rows: list[tuple[int, dict[str, str]]],
    mapping: dict[str, str | None],
    existing: Existing,
    *,
    product_refs_in_file: set[str],
    duplicate_policy: str,
) -> list[RowVerdict]:
    """The Variants sheet: price is required, SKU and barcode must be unique and unclaimed."""
    verdicts: list[RowVerdict] = []
    sku_seen: dict[str, int] = {}
    barcode_seen: dict[str, int] = {}
    combo_seen: dict[tuple[str, str, str], int] = {}
    for number, row in rows:
        v = RowVerdict(SHEET_VARIANTS, number)
        ref = _try(v, "product_ref", _product_ref, _get(row, mapping, "product_ref"), "")
        sku = _try(
            v, "sku", n.parse_code, _get(row, mapping, "sku"), field="sku", max_len=n.SKU_MAX
        )
        barcode = _try(
            v,
            "barcode",
            n.parse_code,
            _get(row, mapping, "barcode"),
            field="barcode",
            max_len=n.BARCODE_MAX,
        )
        price = _try(v, "price", n.parse_price, _get(row, mapping, "price"))
        cost = _try(v, "cost", n.parse_cost, _get(row, mapping, "cost"))
        color = n.clean_text(_get(row, mapping, "color")) or None
        size = n.clean_text(_get(row, mapping, "size")) or None

        if (
            ref is not None
            and ref not in product_refs_in_file
            and ref not in existing.product_slugs
        ):
            v.errors.append(
                RowError(
                    "product_ref", "unknown_product", f"no product '{ref}' in the file or shop"
                )
            )
        if sku is None and barcode is None and not (color or size):
            v.errors.append(
                RowError("sku", "no_identity", "give a SKU, a barcode, or a colour/size")
            )
        if sku is not None:
            if sku in sku_seen:
                v.errors.append(
                    RowError(
                        "sku", "duplicate_in_file", f"SKU repeated, first on row {sku_seen[sku]}"
                    )
                )
            else:
                sku_seen[sku] = number
            owner = existing.sku_owner.get(sku)
            if owner is not None and ref is not None and owner != ref:
                v.errors.append(
                    RowError(
                        "sku", "sku_belongs_to_other_product", f"SKU already used by '{owner}'"
                    )
                )
        if barcode is not None:
            if barcode in barcode_seen:
                v.errors.append(
                    RowError(
                        "barcode",
                        "duplicate_in_file",
                        f"barcode repeated, first on row {barcode_seen[barcode]}",
                    )
                )
            else:
                barcode_seen[barcode] = number
            owner_sku = existing.barcode_owner.get(barcode)
            if owner_sku is not None and owner_sku != sku:
                v.errors.append(
                    RowError("barcode", "barcode_taken", f"barcode already on SKU '{owner_sku}'")
                )
        if ref is not None and sku is None:
            # without a SKU the colour/size pair is the only thing telling two variants apart
            combo = (ref, (color or "").lower(), (size or "").lower())
            if combo in combo_seen:
                v.errors.append(
                    RowError(
                        "color",
                        "duplicate_in_file",
                        f"same colour and size as row {combo_seen[combo]}",
                    )
                )
            else:
                combo_seen[combo] = number
        if v.ok:
            v.values = {
                "product_ref": ref,
                "sku": sku,
                "barcode": barcode,
                "price": price,
                "cost": cost,
                "color": color,
                "size": size,
            }
            v.action = _action(sku is not None and sku in existing.sku_owner, duplicate_policy)
        verdicts.append(v)
    return verdicts


def validate_stock(
    rows: list[tuple[int, dict[str, str]]],
    mapping: dict[str, str | None],
    existing: Existing,
    *,
    skus_in_file: set[str],
    known_skus: set[str],
    default_warehouse: str | None,
) -> list[RowVerdict]:
    """Opening stock: a known SKU, a real warehouse, a whole quantity, once per (SKU, warehouse)."""
    verdicts: list[RowVerdict] = []
    seen: dict[tuple[str, str], int] = {}
    for number, row in rows:
        v = RowVerdict(SHEET_STOCK, number)
        sku = _try(
            v, "sku", n.parse_code, _get(row, mapping, "sku"), field="sku", max_len=n.SKU_MAX
        )
        qty = _try(v, "quantity", n.parse_quantity, _get(row, mapping, "quantity"))
        wh = n.clean_text(_get(row, mapping, "warehouse")) or default_warehouse
        if sku is None:
            v.errors.append(RowError("sku", "required", "sku is required"))
        elif sku not in skus_in_file and sku not in known_skus:
            v.errors.append(RowError("sku", "unknown_sku", f"no variant with SKU '{sku}'"))
        if wh is None:
            v.errors.append(RowError("warehouse", "required", "warehouse is required"))
        elif wh not in existing.warehouse_codes:
            v.errors.append(RowError("warehouse", "unknown_warehouse", f"no warehouse '{wh}'"))
        if sku is not None and wh is not None:
            key = (sku, wh)
            if key in seen:
                v.errors.append(
                    RowError(
                        "sku", "duplicate_in_file", f"same SKU and warehouse as row {seen[key]}"
                    )
                )
            else:
                seen[key] = number
            if key in existing.opening_stock_done:
                v.errors.append(
                    RowError(
                        "sku",
                        "opening_stock_already_set",
                        "opening stock was already recorded for this SKU and warehouse",
                    )
                )
        if v.ok:
            v.values = {"sku": sku, "warehouse": wh, "quantity": qty}
            v.action = "create"
        verdicts.append(v)
    return verdicts


MAX_IMAGES_PER_SKU = 10  # a gallery, not a dump: a typo that repeats a row must not add 500


def validate_images(
    rows: list[tuple[int, dict[str, str]]],
    mapping: dict[str, str | None],
    *,
    skus_in_file: set[str],
    known_skus: set[str],
    already_attached: set[tuple[str, str]],
) -> list[RowVerdict]:
    """A picture for a SKU: the SKU must exist (or be created by this file), the link must be a
    well-formed http(s) one, and the same (SKU, link) is attached once.

    ``already_attached`` holds (sku, link) pairs the shop already has, so a re-run of the same
    file is a skip instead of a second copy of every photo.
    """
    verdicts: list[RowVerdict] = []
    seen: dict[tuple[str, str], int] = {}
    per_sku: dict[str, int] = {}
    for number, row in rows:
        v = RowVerdict(SHEET_IMAGES, number)
        sku = _try(
            v, "sku", n.parse_code, _get(row, mapping, "sku"), field="sku", max_len=n.SKU_MAX
        )
        url = _try(v, "file_name", n.parse_image_url, _get(row, mapping, "file_name"))
        if sku is None:
            v.errors.append(RowError("sku", "required", "sku is required"))
        elif sku not in skus_in_file and sku not in known_skus:
            v.errors.append(RowError("sku", "unknown_sku", f"no variant with SKU '{sku}'"))
        if sku is not None and url is not None:
            key = (sku, url)
            if key in seen:
                v.errors.append(
                    RowError(
                        "file_name",
                        "duplicate_in_file",
                        f"same SKU and image as row {seen[key]}",
                    )
                )
            else:
                seen[key] = number
                per_sku[sku] = per_sku.get(sku, 0) + 1
                if per_sku[sku] > MAX_IMAGES_PER_SKU:
                    v.errors.append(
                        RowError(
                            "sku",
                            "too_many_images",
                            f"more than {MAX_IMAGES_PER_SKU} images for this SKU",
                        )
                    )
        if v.ok:
            v.values = {"sku": sku, "url": url}
            v.action = "skip" if (sku, url) in already_attached else "create"
        verdicts.append(v)
    return verdicts


def validate_item_codes(
    rows: list[tuple[int, dict[str, str]]],
    mapping: dict[str, str | None],
    *,
    skus_in_file: set[str],
    known_skus: set[str],
    existing: dict[tuple[str, str], str],
    held_by_sku: dict[tuple[str, str], str] | None = None,
) -> list[RowVerdict]:
    """A tax item code (EGS or GS1) for a SKU.

    The SKU must exist (or be created by this file). ``existing`` maps ``(type, code)`` to the SKU
    that already holds it: the same code on the same SKU is a skip (a re-run adds nothing), and on
    a DIFFERENT SKU it is refused, never moved, because a code on the wrong variant would put the
    wrong goods on a legal receipt. One variant carries one code per type, and one code belongs to
    one variant: ``held_by_sku`` maps ``(type, SKU)`` to the code a variant already carries, so a
    different code for a type it already has is refused instead of silently adding a second.
    """
    held_by_sku = held_by_sku or {}
    verdicts: list[RowVerdict] = []
    seen_code: dict[tuple[str, str], tuple[int, str]] = {}
    seen_type: dict[tuple[str, str], int] = {}
    for number, row in rows:
        v = RowVerdict(SHEET_ITEM_CODES, number)
        sku = _try(
            v, "sku", n.parse_code, _get(row, mapping, "sku"), field="sku", max_len=n.SKU_MAX
        )
        kind = _try(v, "code_type", n.parse_item_code_type, _get(row, mapping, "code_type"))
        code = None
        if kind is not None:
            code = _try(v, "code", n.parse_item_code, kind, _get(row, mapping, "code"))
        elif not _get(row, mapping, "code"):
            v.errors.append(RowError("code", "required", "code is required"))
        if sku is None:
            if not any(e.field == "sku" for e in v.errors):
                v.errors.append(RowError("sku", "required", "sku is required"))
        elif sku not in skus_in_file and sku not in known_skus:
            v.errors.append(RowError("sku", "unknown_sku", f"no variant with SKU '{sku}'"))
        if sku is not None and kind is not None and code is not None:
            key = (kind, code)
            owner = existing.get(key)
            if key in seen_code:
                v.errors.append(
                    RowError(
                        "code", "duplicate_in_file", f"same {kind} code as row {seen_code[key][0]}"
                    )
                )
            elif owner is not None and owner != sku:
                v.errors.append(
                    RowError("code", "code_taken", f"this {kind} code is already on SKU '{owner}'")
                )
            elif held_by_sku.get((kind, sku), code) != code:
                v.errors.append(
                    RowError(
                        "code",
                        "second_code_for_type",
                        f"SKU '{sku}' already has a {kind} code ({held_by_sku[(kind, sku)]})",
                    )
                )
            elif (kind, sku) in seen_type and owner != sku:
                v.errors.append(
                    RowError(
                        "code_type",
                        "second_code_for_type",
                        f"SKU '{sku}' already has a {kind} code on row {seen_type[(kind, sku)]}",
                    )
                )
            else:
                seen_code[key] = (number, sku)
                seen_type.setdefault((kind, sku), number)
        if v.ok:
            v.values = {"sku": sku, "code_type": kind, "code": code}
            v.action = "skip" if existing.get((kind, code)) == sku else "create"
        verdicts.append(v)
    return verdicts


def summarize(verdicts: list[RowVerdict]) -> dict[str, object]:
    """Counters for the preview: how many rows would do what, and which errors dominate."""
    actions: dict[str, int] = defaultdict(int)
    codes: dict[str, int] = defaultdict(int)
    invalid = 0
    for v in verdicts:
        if v.ok:
            actions[v.action or "create"] += 1
        else:
            invalid += 1
            for e in v.errors:
                codes[e.code] += 1
    return {
        "total": len(verdicts),
        "valid": len(verdicts) - invalid,
        "invalid": invalid,
        "create": actions["create"],
        "update": actions["update"],
        "skip": actions["skip"],
        "error_codes": dict(sorted(codes.items(), key=lambda kv: -kv[1])),
    }


__all__ = [
    "DUPLICATE_POLICIES",
    "Existing",
    "RowError",
    "RowVerdict",
    "summarize",
    "validate_images",
    "validate_item_codes",
    "validate_products",
    "validate_stock",
    "validate_variants",
]
