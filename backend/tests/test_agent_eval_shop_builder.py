"""The shop builder must produce data the REAL tools can read. If it silently built nothing,
every golden case would run against an empty shop and 'passes' would mean nothing."""

from __future__ import annotations

import json

from app.modules.ai.agents.customer import tools as customer_tools
from tests.agent_eval.cases_core import CASES
from tests.agent_eval.shop_builder import build_shop


def _case(case_id: str):
    return next(c for c in CASES if c.id == case_id)


async def test_a_written_policy_reaches_get_store_info(db, tenant_ctx) -> None:
    case = _case("policy-written-exchange-is-quoted-exactly")
    await build_shop(db, tenant_ctx.tenant_id, case.store)

    info = await customer_tools._get_store_info(db, tenant_ctx.tenant_id, question="الاستبدال")

    assert "14 يوم" in json.dumps(info, ensure_ascii=False)


async def test_an_unwritten_policy_is_absent_not_invented(db, tenant_ctx) -> None:
    case = _case("policy-unwritten-exchange")
    await build_shop(db, tenant_ctx.tenant_id, case.store)

    info = await customer_tools._get_store_info(db, tenant_ctx.tenant_id, question="الاستبدال")

    assert "14" not in json.dumps(info, ensure_ascii=False)


async def test_catalogue_shows_price_and_real_stock(db, tenant_ctx) -> None:
    case = _case("out-of-stock-size-offers-real-alternative")
    await build_shop(db, tenant_ctx.tenant_id, case.store)

    found = await customer_tools._search_catalog(db, tenant_ctx.tenant_id, query="تيشيرت")
    blob = json.dumps(found, ensure_ascii=False, default=str)

    assert "250" in blob
    assert "300" in blob  # the XL variant exists with its own price, though it has no stock
