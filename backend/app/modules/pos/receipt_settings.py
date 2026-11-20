"""What the shop owner decided about how a receipt looks and what it promises.

The receipt used to carry the same wording, paper width and exchange period for every shop. The
owner sets these in the shop settings, so the receipt reads them: a shop that gives 30 days to
exchange prints 30, not the 14 the code once said.

The values are resolved at the till the receipt was issued on (register, then its profile, branch
and the shop), so a branch can print its own footer or a till its own paper. The reply carries
final values, never a rule for the screen to apply: no shop policy lives in the client.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.service import SettingsService

# The keys a receipt reads. Kept literal so the settings guard sees them.
_KEYS = (
    "business.trade_name",
    "business.legal_name",
    "business.address.line1",
    "business.address.city",
    "business.phone",
    "business.tax_id",
    "print.paper_width",
    "print.show_logo",
    "print.header_text",
    "print.footer_text",
    "print.copies",
    "print.show_tax_detail",
    "pos.exchange_max_days",
)

# Millimetres the printer sees. "a4" is a sheet printer, not a till roll: use the wide roll.
_PAPER_MM = {"58mm": 58, "80mm": 80, "a4": 80}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _whole(value: object, *, default: int, low: int, high: int) -> int:
    """A setting that should be a whole number in a range. Anything else falls back, never raises:
    a receipt must still print when a setting holds something unexpected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return max(low, min(high, int(value)))


async def receipt_settings(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    register_id: UUID | None,
) -> dict:
    """The shop's receipt settings, resolved at the register the receipt was issued on."""
    svc = SettingsService(session, tenant_id)
    if register_id is None:
        resolved = await svc.resolve_many(list(_KEYS))
    else:
        resolved = await svc.resolve_many(list(_KEYS), scope="register", scope_id=register_id)
    v = {key: r.value for key, r in resolved.items()}

    name = _text(v["business.trade_name"]) or _text(v["business.legal_name"])
    paper = v["print.paper_width"] if v["print.paper_width"] in _PAPER_MM else "80mm"
    return {
        "shop_name": name or None,
        "address": ", ".join(
            p for p in (_text(v["business.address.line1"]), _text(v["business.address.city"])) if p
        )
        or None,
        "phone": _text(v["business.phone"]) or None,
        "tax_id": _text(v["business.tax_id"]) or None,
        "paper_mm": _PAPER_MM[paper],
        "show_logo": v["print.show_logo"] is True,
        "header_text": _text(v["print.header_text"]) or None,
        "footer_text": _text(v["print.footer_text"]) or None,
        "copies": _whole(v["print.copies"], default=1, low=1, high=5),
        "show_tax_detail": v["print.show_tax_detail"] is True,
        # 0 = "no exchanges": the receipt says nothing about exchange instead of promising 0 days.
        "exchange_days": _whole(v["pos.exchange_max_days"], default=0, low=0, high=365),
    }
