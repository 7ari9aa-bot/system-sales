"""The Fihrist Sites client: allow-lists, filter safety, and "off until configured".

DB-free. The HTTP layer is replaced with ``httpx.MockTransport`` so the tests can assert
the exact request that WOULD reach the platform, which is what proves a crafted value
cannot add a filter or reach a column that is not on the list.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.modules.platform.services import sites_platform as sp

REAL_CLIENT = httpx.AsyncClient  # captured before any fixture replaces it
KEY = "service-role-SECRET-DO-NOT-LEAK"
SEEN: list[httpx.Request] = []


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "sites_platform_supabase_url", "https://abc.supabase.co", raising=False)
    monkeypatch.setattr(s, "sites_platform_service_key", KEY, raising=False)
    SEEN.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        SEEN.append(request)
        if request.method == "PATCH":
            return httpx.Response(200, json=[{"x": 1}])
        if "count=exact" in request.headers.get("prefer", ""):
            return httpx.Response(200, json=[], headers={"content-range": "0-0/7"})
        return httpx.Response(200, json=[{"id": "1"}])

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(sp.httpx, "AsyncClient", factory)


async def test_off_by_default_every_call_is_refused(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "sites_platform_supabase_url", "", raising=False)
    monkeypatch.setattr(s, "sites_platform_service_key", "", raising=False)
    assert sp.is_configured() is False
    with pytest.raises(sp.SitesPlatformNotConfigured):
        await sp.select("sites")
    with pytest.raises(sp.SitesPlatformNotConfigured):
        await sp.update("designs", {"key": "a"}, {"is_listed": True})


async def test_a_non_https_url_is_refused(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "sites_platform_supabase_url", "http://abc.supabase.co", raising=False)
    monkeypatch.setattr(s, "sites_platform_service_key", KEY, raising=False)
    with pytest.raises(sp.SitesPlatformNotConfigured):
        await sp.select("sites")


async def test_only_listed_tables_and_columns_are_readable(configured):
    with pytest.raises(sp.SitesPlatformError):
        await sp.select("auth.users")
    with pytest.raises(sp.SitesPlatformError):
        await sp.select("site_customers")  # holds customer names/phones: never listed
    with pytest.raises(sp.SitesPlatformError):
        await sp.select("orders", eq={"customer_name": "x"})
    with pytest.raises(sp.SitesPlatformError):
        await sp.select("sites", order="-password")
    assert SEEN == []  # none of those ever left the process


async def test_personal_data_columns_are_never_selected(configured):
    for table in ("orders", "contact_messages", "products", "coupons", "sites"):
        await sp.select(table)
    for req in SEEN:
        cols = req.url.params["select"]
        for forbidden in (
            "customer_name",
            "phone",
            "address",
            "contact",
            "message",
            "note",
            "name,contact",
        ):
            assert forbidden not in cols.split(","), (req.url.path, cols)


async def test_a_value_cannot_add_or_change_a_filter(configured):
    evil = "x&site_id=neq.0&select=*&or=(id.gt.0)"
    await sp.select("sites", eq={"slug": evil})
    url = str(SEEN[-1].url)
    assert "site_id=neq" not in url and "or=(" not in url
    assert SEEN[-1].url.params["slug"] == "eq." + evil  # sent as ONE encoded value
    assert SEEN[-1].url.params["select"] != "*"


async def test_in_filter_items_are_quoted_so_commas_and_parens_stay_data(configured):
    await sp.select("sites", in_=("id", ["a,b)&x=1", 'c"d', "e\\f"]))
    value = SEEN[-1].url.params["id"]
    # one list, three items: the separator characters inside an item cannot end it
    assert value == 'in.("a,b)&x=1","c\\"d","e\\\\f")'
    assert "x" not in {k for k in SEEN[-1].url.params.keys()} - {"select", "id", "limit"}


async def test_a_plain_value_is_not_double_encoded(configured):
    await sp.select("sites", eq={"slug": "my shop+1"})
    assert SEEN[-1].url.params["slug"] == "eq.my shop+1"  # what PostgREST will actually decode


async def test_uuid_and_key_validators_reject_anything_else():
    good = "3bcfd644-e959-4a69-8189-d0e4da86a14d"
    assert sp.uuid_or_none(good) == good
    assert sp.uuid_or_none(good.upper()) == good
    for bad in ("", "x", good + "&a=b", good[:-1], "1' or '1'='1", None, 5, "../", good + "\n"):
        assert sp.uuid_or_none(bad) is None, bad
    assert sp.key_or_none("funny-baby-2") == "funny-baby-2"
    for bad in ("", "A", "a b", "a&b", "-x", "a" * 65, "a/b", "__proto__x\n"):
        assert sp.key_or_none(bad) is None, bad


async def test_limit_is_clamped(configured):
    await sp.select("sites", limit=10**9)
    assert SEEN[-1].url.params["limit"] == "500"
    await sp.select("sites", limit=-5)
    assert SEEN[-1].url.params["limit"] == "1"


async def test_writes_only_touch_allow_listed_columns_and_never_without_a_filter(configured):
    with pytest.raises(sp.SitesPlatformError):
        await sp.update("designs", {"key": "a"}, {"price_egp": 5, "origin": "https://evil"})
    with pytest.raises(sp.SitesPlatformError):
        await sp.update("sites", {"id": "x"}, {"owner_id": "y"})
    with pytest.raises(sp.SitesPlatformError):
        await sp.update("orders", {"id": "x"}, {"status": "ملغي"})  # not writable from here at all
    with pytest.raises(sp.SitesPlatformError):
        await sp.update("designs", {}, {"is_listed": True})  # no filter would change EVERY row
    with pytest.raises(sp.SitesPlatformError):
        await sp.update("designs", {"key": "a"}, {})
    assert SEEN == []
    assert await sp.update("designs", {"key": "a"}, {"is_listed": True}) == 1
    assert SEEN[-1].method == "PATCH" and SEEN[-1].url.params["key"] == "eq.a"


async def test_there_is_no_delete_in_the_module():
    assert not hasattr(sp, "delete")
    assert "DELETE" not in open(sp.__file__, encoding="utf8").read().upper().replace(
        "NEVER DELETES", ""
    )


async def test_the_key_is_sent_as_a_header_but_never_in_the_url_or_in_errors(
    configured, monkeypatch
):
    await sp.select("sites")
    req = SEEN[-1]
    assert req.headers["apikey"] == KEY and KEY not in str(req.url)

    def boom(request):
        return httpx.Response(401, text=f"bad key {KEY}")

    monkeypatch.setattr(
        sp.httpx,
        "AsyncClient",
        lambda *a, **k: REAL_CLIENT(*a, **{**k, "transport": httpx.MockTransport(boom)}),
    )
    with pytest.raises(sp.SitesPlatformError) as exc:
        await sp.select("sites")
    assert KEY not in str(exc.value) and "bad key" not in str(exc.value)


async def test_count_only_reads_the_total_from_the_header(configured):
    assert (
        await sp.select(
            "orders", eq={"site_id": "3bcfd644-e959-4a69-8189-d0e4da86a14d"}, count_only=True
        )
        == 7
    )


async def test_neq_and_gte_filters_reach_the_platform_encoded_and_only_on_listed_columns(
    configured,
):
    await sp.select(
        "orders",
        eq={"site_id": "3bcfd644-e959-4a69-8189-d0e4da86a14d"},
        neq={"status": "ملغي"},
    )
    await sp.select("page_stats", gte={"day": "2026-10-12"})
    q1, q2 = SEEN[-2].url.params, SEEN[-1].url.params
    assert q1["status"] == "neq.ملغي"
    assert q2["day"] == "gte.2026-10-12"
    with pytest.raises(sp.SitesPlatformError):  # a column that is not on the list
        await sp.select("orders", neq={"customer_name": "x"})
    with pytest.raises(sp.SitesPlatformError):
        await sp.select("page_stats", gte={"phone": "2026-10-12"})


@pytest.mark.parametrize(
    "evil",
    ["a,b", "x)&select=*", "1.or.(id.neq.0)", "a b", "x&limit=1000", "", "q" * 41, "a=b", "x;y"],
)
async def test_a_neq_or_gte_value_cannot_add_a_second_filter(configured, evil):
    """The value is checked BEFORE the request exists: nothing reaches the platform."""
    before = len(SEEN)
    for group in ("neq", "gte"):
        with pytest.raises(sp.SitesPlatformError):
            await sp.select("orders", **{group: {"status": evil}})
    assert len(SEEN) == before


async def test_tables_that_hold_customer_personal_data_are_still_unreadable(configured):
    """Not even for a count: a service key opens every column, so the table itself stays off."""
    for table in ("site_customers", "newsletter_subscribers", "profiles"):
        with pytest.raises(sp.SitesPlatformError):
            await sp.select(table, count_only=True)
    assert SEEN == []
