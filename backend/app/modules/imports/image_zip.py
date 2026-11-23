"""A folder of pictures, matched to the shop by file name.

Merchants keep product photos in folders named after the item: ``TEE-BK-M.jpg``,
``TEE-BK-M-2.jpg`` for a second angle, sometimes ``TEE-BK-M (1).jpg`` because the camera app
renamed it. Uploading them one product at a time is the slowest part of opening a season.

This module only decides which picture belongs to which SKU and in what order — it stores nothing
and touches no database. The caller (the endpoint) keeps the bytes, checks they are real pictures
and attaches them through the catalog, so the rules for an image are the same as an upload by hand.
"""

from __future__ import annotations

import re
import unicodedata

from app.modules.catalog.limits import MAX_IMAGES_PER_SKU as CATALOG_MAX_IMAGES_PER_SKU

# الحد اللي بيحكم عدد صور الصنف: نفس رقم ورقة الصور في مركز الاستيراد والرفع اليدوي
# (المصدر الوحيد في catalog/limits.py).
MAX_IMAGES_PER_SKU = CATALOG_MAX_IMAGES_PER_SKU
MAX_ENTRIES = 5_000
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

# "-2" أو " (1)" أو "_2" في آخر الاسم = زاوية تانية لنفس الصنف، مش SKU مختلف.
_ANGLE_SUFFIX = re.compile(r"[\s_\-]*(?:\(\d{1,2}\)|\[\d{1,2}\]|\d{1,2})$")


def sku_from_name(path: str) -> str:
    """The name a file claims, extension dropped and sub-folders ignored. "" when not a picture.

    Sub-folders are ignored (a folder per supplier still names the file after the item) and case is
    kept as the merchant wrote it. A trailing angle marker (``-2``, ``(1)``) is NOT removed here:
    ``TEE-1`` may be a real SKU, so the exact name is tried first and the base only as a fallback
    (``sku_candidates``).
    """
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return ""
    lowered = name.lower()
    for ext in IMAGE_EXTENSIONS:
        if lowered.endswith(ext):
            name = name[: -len(ext)]
            break
    else:
        return ""
    return unicodedata.normalize("NFKC", name).strip()


def sku_candidates(path: str) -> list[str]:
    """What this picture may belong to: the exact name first, then the name without an angle mark.

    ``TEE-BK-M-2.jpg`` (a second angle) and ``TEE-BK-M (1).jpg`` (a phone copy) both fall back to
    ``TEE-BK-M``, but only after the exact SKU ``TEE-BK-M-2`` has been looked for — so a shop that
    really sells ``TEE-1`` gets its own picture.
    """
    exact = sku_from_name(path)
    if not exact:
        return []
    base = _ANGLE_SUFFIX.sub("", exact).strip()
    return [exact] if not base or base == exact else [exact, base]


def plan_images(paths: list[str], known: set[str] | None = None) -> dict[str, list[str]]:
    """SKU (upper-cased key) -> its picture paths, in the order the archive lists them.

    With ``known`` (the shop's SKUs) a file is matched by its exact name first and by the base name
    second; without it, files are grouped by their exact name only. Anything that is not a picture
    is left out; the caller reports those separately so the merchant sees what did not land.
    """
    plan: dict[str, list[str]] = {}
    for path in paths:
        for candidate in sku_candidates(path):
            key = candidate.upper()
            if known is None:
                plan.setdefault(key, []).append(path)
                break
            if key in known:
                plan.setdefault(key, []).append(path)
                break
    return plan


_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

# نفس فحص التوقيع اللي بيمشي على أي صورة بتدخل المتجر: الامتداد لوحده مش دليل.
_SIGNATURES = {
    "image/jpeg": lambda d: d.startswith(b"\xff\xd8\xff"),
    "image/png": lambda d: d.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/gif": lambda d: d.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP",
    "image/bmp": lambda d: d.startswith(b"BM"),
}


def content_type_for(path: str) -> str:
    lowered = str(path or "").lower()
    for ext, kind in _CONTENT_TYPES.items():
        if lowered.endswith(ext):
            return kind
    return ""


def looks_like_image(content_type: str, data: bytes) -> bool:
    check = _SIGNATURES.get((content_type or "").lower())
    return bool(data) and check is not None and check(data)
