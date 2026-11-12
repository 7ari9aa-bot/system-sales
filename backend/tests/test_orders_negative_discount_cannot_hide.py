"""A negative invoice discount is refused even beside a line discount that outweighs it.

``discount_total`` was judged only after being added to the line discounts, so -40 next to a 50%
line netted to a positive 10 and went through. The receipt then carried a 50% line discount and a
negative one that cancelled it, and any report on line discounts was wrong. Judged on its own now.
"""

from __future__ import annotations

import pytest

from app.modules.errors import ValidationError
from tests.test_pos_discount_ceiling import _sell, _till
from tests.test_pos_phase6 import _sellable_variant


@pytest.mark.parametrize("typed", ["-0.01", "-40.00", "-500"])
async def test_a_negative_discount_is_refused_even_with_a_line_discount(db, tenant_ctx, typed):
    register, _ = await _till(db, tenant_ctx, ceiling=None)
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    with pytest.raises(ValidationError) as caught:
        await _sell(db, tenant_ctx, register, variant, discount_total=typed, pct="50")
    assert "negative" in str(caught.value)


async def test_a_negative_discount_alone_is_still_refused(db, tenant_ctx):
    register, _ = await _till(db, tenant_ctx, ceiling=None)
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    with pytest.raises(ValidationError):
        await _sell(db, tenant_ctx, register, variant, discount_total="-1.00")


async def test_zero_and_normal_discounts_are_untouched(db, tenant_ctx):
    register, _ = await _till(db, tenant_ctx, ceiling=None)
    variant = await _sellable_variant(db, tenant_ctx, price="100.00")
    assert (await _sell(db, tenant_ctx, register, variant, discount_total="0"))[
        "grand_total"
    ] == "100.00"
    assert (await _sell(db, tenant_ctx, register, variant, discount_total="10.00", pct="10"))[
        "grand_total"
    ] == "80.00"
