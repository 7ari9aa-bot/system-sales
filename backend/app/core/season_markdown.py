"""Season markdown: take a percent off every size of one season, after the owner has seen it.

The owner picks a season (and optionally a brand) and a percent. ``preview`` shows every size's old
price, new price and whether the new price is under what the shop paid; nothing is written.
``apply`` writes exactly that set, or nothing.

* Money is ``Decimal`` end to end. The percent comes in as text (``"15"``, ``"12.5"``), never a
  float, and ``new = old * (100 - percent) / 100`` is rounded half up to the cent.
* The price a till sells at is ``product_variants.price``; that is the only column changed. The
  price-tier table is a separate quantity-break list the till does not read, so it is left alone.
* The token is a signature over the shop, the season, the percent and every (variant, old price,
  new price). ``apply`` rebuilds the set from the live catalog and refuses (409) if it no longer
  matches the token: a price changed, a size was added or deactivated, or the token is someone
  else's. So what the owner approved is exactly what is written.
* The rows are locked (``FOR UPDATE``) before they are re-read, so two applies at once cannot both
  succeed: the second sees the changed prices, its token no longer matches, and it gets the 409.
* A price never goes to zero or below: a size whose new price would round under 0.01 keeps 0.01 and
  is flagged ``at_floor``. A new price under the known cost is flagged ``below_cost``; it is shown,
  not blocked, because selling under cost to clear a season is the owner's call. Unknown cost is
  never treated as zero: it is ``cost_known`` false and never ``below_cost``.
* One audit row is written for the whole markdown (who, season, percent, counts), in the same
  transaction as the prices.

A shop that never calls this is unchanged: nothing here runs on its own.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_row
from app.core.config import get_settings
from app.core.profit_report import ProfitCtx
from app.modules.catalog.apparel.matrix import COLOR_AXIS, SIZE_AXIS
from app.modules.catalog.models import Product, ProductVariant
from app.modules.errors import ConflictError, ValidationError

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")
MIN_PERCENT = Decimal("0.01")
MAX_PERCENT = Decimal("90")

_VariantCost = table(
    "variant_costs",
    column("tenant_id"),
    column("variant_id"),
    column("avg_cost"),
)


def parse_percent(value: object) -> Decimal:
    """The percent as an exact decimal, 0.01 to 90, at most two decimals. Never a float."""
    if isinstance(value, float) or isinstance(value, bool) or value is None:
        raise ValidationError('percent must be sent as text, for example "15" or "12.5"')
    try:
        pct = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError("percent must be a number") from None
    if not pct.is_finite():
        raise ValidationError("percent must be a number")
    if pct != pct.quantize(_CENT):
        raise ValidationError("percent can have at most two decimals")
    if pct < MIN_PERCENT or pct > MAX_PERCENT:
        raise ValidationError("percent must be between 0.01 and 90")
    return pct


def marked_down(old: Decimal, percent: Decimal) -> Decimal:
    """``old`` less ``percent``, to the cent, half up. Exact: no float anywhere."""
    return (old * (_HUNDRED - percent) / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)


def _sign(tenant_id: UUID, season: str, percent: Decimal, lines: list[tuple[str, str, str]]) -> str:
    body = json.dumps(
        {"t": str(tenant_id), "s": season, "p": str(percent), "l": lines},
        sort_keys=True,
        separators=(",", ":"),
    )
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()


class SeasonMarkdownService:
    @staticmethod
    async def _plan(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        season: str,
        percent: Decimal,
        brand_id: UUID | None,
        lock: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, ProductVariant]]:
        wanted = season.strip()
        if not wanted:
            raise ValidationError("season is required")
        stmt = (
            select(
                ProductVariant,
                Product.title.label("model"),
                Product.brand_id.label("brand_id"),
                ProductVariant.option_values[SIZE_AXIS].astext.label("size"),
                ProductVariant.option_values[COLOR_AXIS].astext.label("colour"),
                _VariantCost.c.avg_cost.label("avg_cost"),
            )
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(
                _VariantCost,
                (_VariantCost.c.variant_id == ProductVariant.id)
                & (_VariantCost.c.tenant_id == tenant_id),
            )
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.is_active.is_(True),
                # trimmed on both sides: a season saved with stray spaces is still that season
                func.lower(func.trim(Product.season)) == wanted.lower(),
            )
            .order_by(Product.title, ProductVariant.id)
        )
        if brand_id is not None:
            stmt = stmt.where(Product.brand_id == brand_id)
        if lock:
            stmt = stmt.with_for_update(of=ProductVariant)
        found = (await session.execute(stmt)).all()

        rows: list[dict[str, Any]] = []
        live: dict[str, ProductVariant] = {}
        for r in found:
            v: ProductVariant = r.ProductVariant
            old = Decimal(v.price)
            new = marked_down(old, percent)
            at_floor = new < _CENT
            if at_floor:
                new = _CENT
            cost = None if r.avg_cost is None else Decimal(r.avg_cost)
            rows.append(
                {
                    "variant_id": str(v.id),
                    "product_id": str(v.product_id),
                    "model": r.model,
                    "colour": r.colour,
                    "size": r.size,
                    "old_price": str(old.quantize(_CENT, rounding=ROUND_HALF_UP)),
                    "new_price": str(new),
                    "unit_cost": None if cost is None else str(cost.quantize(_CENT)),
                    "cost_known": cost is not None,
                    "below_cost": cost is not None and new < cost,
                    "at_floor": at_floor,
                }
            )
            live[str(v.id)] = v
        return rows, live

    @staticmethod
    def _token(tenant_id: UUID, season: str, percent: Decimal, rows: list[dict[str, Any]]) -> str:
        lines = sorted((r["variant_id"], r["old_price"], r["new_price"]) for r in rows)
        return _sign(tenant_id, season.strip().lower(), percent, lines)

    @staticmethod
    def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "variants": len(rows),
            "products": len({r["product_id"] for r in rows}),
            "below_cost": sum(1 for r in rows if r["below_cost"]),
            "at_floor": sum(1 for r in rows if r["at_floor"]),
            "without_cost": sum(1 for r in rows if not r["cost_known"]),
        }

    @staticmethod
    async def preview(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        season: str,
        percent: object,
        brand_id: UUID | None = None,
    ) -> dict[str, Any]:
        pct = parse_percent(percent)
        rows, _ = await SeasonMarkdownService._plan(
            session, tenant_id, season=season, percent=pct, brand_id=brand_id, lock=False
        )
        return {
            "season": season.strip(),
            "percent": str(pct),
            "rows": rows,
            "totals": SeasonMarkdownService._totals(rows),
            "token": SeasonMarkdownService._token(tenant_id, season, pct, rows),
        }

    @staticmethod
    async def apply(
        session: AsyncSession,
        tenant_id: UUID,
        actor_user_id: UUID | None,
        *,
        season: str,
        percent: object,
        token: str,
        brand_id: UUID | None = None,
    ) -> dict[str, Any]:
        pct = parse_percent(percent)
        # Lock first, then read: a second apply waits here and then sees the new prices.
        rows, live = await SeasonMarkdownService._plan(
            session, tenant_id, season=season, percent=pct, brand_id=brand_id, lock=True
        )
        expected = SeasonMarkdownService._token(tenant_id, season, pct, rows)
        if not rows or not hmac.compare_digest(expected, token or ""):
            raise ConflictError(
                "the catalog changed since the preview, or nothing matches: preview again"
            )
        before: dict[str, str] = {}
        for r in rows:
            variant = live[r["variant_id"]]
            before[r["variant_id"]] = r["old_price"]
            variant.price = Decimal(r["new_price"])
        await session.flush()
        totals = SeasonMarkdownService._totals(rows)
        await write_audit_row(
            session,
            tenant_id,
            actor_user_id,
            "catalog.season_markdown",
            "season",
            season.strip(),
            before={"percent": None, "prices": before},
            after={
                "percent": str(pct),
                "season": season.strip(),
                "brand_id": str(brand_id) if brand_id else None,
                **totals,
            },
        )
        return {"applied": totals["variants"], "percent": str(pct), "totals": totals}


class _Body(BaseModel):
    season: Annotated[str, Field(min_length=1, max_length=60)]
    percent: Annotated[str, Field(min_length=1, max_length=8)]
    brand_id: UUID | None = None


class _ApplyBody(_Body):
    token: Annotated[str, Field(min_length=1, max_length=128)]


router = APIRouter(prefix="/catalog/season-markdown", tags=["season-markdown"])


@router.post("/preview")
async def season_markdown_preview(ctx: ProfitCtx, body: _Body) -> dict[str, Any]:
    """What a season would cost per size at this percent. Writes nothing."""
    return await SeasonMarkdownService.preview(
        ctx.session,
        ctx.tenant_id,
        season=body.season,
        percent=body.percent,
        brand_id=body.brand_id,
    )


@router.post("/apply")
async def season_markdown_apply(ctx: ProfitCtx, body: _ApplyBody) -> dict[str, Any]:
    """Write the previewed prices, all or nothing. 409 if the catalog moved since the preview."""
    return await SeasonMarkdownService.apply(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        season=body.season,
        percent=body.percent,
        token=body.token,
        brand_id=body.brand_id,
    )
