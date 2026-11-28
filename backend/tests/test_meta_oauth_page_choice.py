"""Choosing which Page to connect when the owner ticked several.

The connect used to take the first Page without asking. Now it pauses, keeps the long-lived user
token server-side (encrypted, once-only ticket, short-lived) and finishes with the Page the owner
picks. These tests need no database: they cover what makes the pause safe.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fakeredis.aioredis import FakeRedis

from app.core.errors import ValidationError
from app.applications.apparel.modules.customers import meta_oauth as mo

TENANT = uuid.uuid4()
USER = str(uuid.uuid4())
USER_TOKEN = "fake-LONG-LIVED-USER-TOKEN-never-shown-to-the-browser"
PAGES = [
    {"id": "111", "name": "Shop One", "access_token": "PAGE-TOKEN-1", "tasks": ["MANAGE"]},
    {"id": "222", "name": "Shop Two", "access_token": "PAGE-TOKEN-2", "tasks": ["MANAGE"]},
    {"id": "333", "name": "Analytics only", "access_token": "PAGE-TOKEN-3", "tasks": ["ANALYZE"]},
]


@pytest.fixture
def redis(monkeypatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(mo, "get_redis", lambda: client)
    return client


async def _park(**over):
    args = {
        "tenant_id": TENANT,
        "user_id": USER,
        "provider": "facebook",
        "user_token": USER_TOKEN,
        "expires_in": 5_183_944,
        "granted": ["pages_messaging"],
        "config_id": "",
        "page_ids": ["111", "222"],
    }
    args.update(over)
    return await mo._park_page_choice(**args)


def test_only_pages_the_operator_can_message_are_offered() -> None:
    offered = mo._messaging_pages(PAGES)
    assert [p["id"] for p in offered] == ["111", "222"]


def test_when_no_page_lists_tasks_they_are_all_offered() -> None:
    bare = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
    assert mo._messaging_pages(bare) == bare


def test_a_page_the_operator_cannot_message_on_is_never_offered() -> None:
    """Meta says (tasks present, no MESSAGING/MANAGE) the operator cannot run chat on it. The old
    fallback returned every Page when none qualified, so an unqualified Page could be connected."""
    only_ads = [{"id": "9", "name": "Ads", "tasks": ["ADVERTISE"]}]
    assert mo._messaging_pages(only_ads) == []


def test_only_the_qualified_pages_are_offered_from_a_mixed_list() -> None:
    mixed = [
        {"id": "9", "name": "Ads", "tasks": ["ADVERTISE"]},
        {"id": "1", "name": "Shop", "tasks": ["MESSAGING", "ANALYZE"]},
        {"id": "2", "name": "Old", "tasks": []},
        {"id": "3", "name": "Older"},
    ]
    assert [p["id"] for p in mo._messaging_pages(mixed)] == ["1", "2", "3"]


def test_the_browser_sees_ids_and_names_never_tokens() -> None:
    choices = mo._page_choices(PAGES)
    assert choices[0] == {"id": "111", "name": "Shop One"}
    assert "PAGE-TOKEN" not in json.dumps(choices)


async def test_the_user_token_is_stored_encrypted_not_in_the_clear(redis) -> None:
    ticket = await _park()
    raw = await redis.get(mo._page_choice_key(ticket))
    assert raw is not None
    assert USER_TOKEN not in raw
    assert "PAGE-TOKEN" not in raw


async def test_the_parked_choice_expires_and_is_never_kept_forever(redis) -> None:
    """It holds the owner's long-lived token (encrypted), so it must always have a deadline."""
    ticket = await _park()
    ttl = await redis.ttl(mo._page_choice_key(ticket))
    assert 0 < ttl <= mo._PAGE_CHOICE_TTL_SECONDS


async def test_a_ticket_round_trips_with_the_secrets_back(redis) -> None:
    ticket = await _park()
    parked = await mo._take_page_choice(ticket)
    assert parked["secrets"]["user_token"] == USER_TOKEN
    assert parked["secrets"]["expires_in"] == 5_183_944
    assert parked["page_ids"] == ["111", "222"]
    assert parked["tenant_id"] == str(TENANT)
    assert parked["user_id"] == USER


async def test_a_ticket_works_only_once(redis) -> None:
    ticket = await _park()
    assert await mo._take_page_choice(ticket) is not None
    assert await mo._take_page_choice(ticket) is None


async def test_an_unknown_ticket_is_refused(redis) -> None:
    assert await mo._take_page_choice("does-not-exist") is None


async def test_two_connects_never_share_a_ticket(redis) -> None:
    assert await _park() != await _park()


# --- the endpoint -----------------------------------------------------------


class _Ctx:
    def __init__(self, tenant_id=TENANT, user_id=USER):
        self.tenant_id = tenant_id
        self.user = type("U", (), {"id": user_id})()


async def _choose(ticket, page_id, ctx=None):
    body = mo.MetaOAuthPageChoiceIn(ticket=ticket, page_id=page_id)
    return await mo.meta_oauth_choose_page(body, session=None, ctx=ctx or _Ctx())


async def test_an_expired_or_unknown_ticket_asks_to_start_again(redis) -> None:
    with pytest.raises(ValidationError, match="expired"):
        await _choose("x" * 24, "111")


async def test_another_tenants_ticket_is_refused_and_burned(redis) -> None:
    ticket = await _park()
    with pytest.raises(ValidationError, match="not started by you"):
        await _choose(ticket, "111", _Ctx(tenant_id=uuid.uuid4()))
    assert await mo._take_page_choice(ticket) is None


async def test_another_users_ticket_is_refused(redis) -> None:
    ticket = await _park()
    with pytest.raises(ValidationError, match="not started by you"):
        await _choose(ticket, "111", _Ctx(user_id=str(uuid.uuid4())))


async def test_a_page_that_was_not_offered_is_refused(redis) -> None:
    """A forged id must not reach another Page the user manages."""
    ticket = await _park()
    with pytest.raises(ValidationError, match="not one of the choices"):
        await _choose(ticket, "333")


async def test_a_page_that_was_not_offered_does_not_burn_the_owners_ticket(redis) -> None:
    """One slip (a wrong id, a double click) must not force the owner to start the OAuth again.

    The ticket is 192 random bits, so keeping it alive after a bad page id gives a guesser
    nothing: they would need the ticket first. Burning it only punished the real owner."""
    ticket = await _park()
    with pytest.raises(ValidationError, match="not one of the choices"):
        await _choose(ticket, "333")

    assert await redis.exists(mo._page_choice_key(ticket)), "the owner can still pick a Page"


async def test_another_users_ticket_is_burned(redis) -> None:
    """Someone else holding this ticket is tampering, not slipping: it dies on the spot."""
    ticket = await _park()
    with pytest.raises(ValidationError, match="not started by you"):
        await _choose(ticket, "111", _Ctx(user_id=str(uuid.uuid4())))

    assert not await redis.exists(mo._page_choice_key(ticket))


async def test_the_owner_can_pick_again_after_a_wrong_page(redis, monkeypatch) -> None:
    ticket = await _park()
    with pytest.raises(ValidationError, match="not one of the choices"):
        await _choose(ticket, "333")

    parked = await mo._take_page_choice(ticket)
    assert parked is not None and "111" in parked["page_ids"]


async def test_a_ticket_still_works_only_once_after_a_good_choice(redis) -> None:
    """Checking before consuming must not open a window for two requests to both succeed."""
    ticket = await _park()
    assert await mo._take_page_choice(ticket) is not None
    with pytest.raises(ValidationError, match="expired"):
        await _choose(ticket, "111")


async def test_two_simultaneous_choices_connect_exactly_one(redis, monkeypatch) -> None:
    """Peeking first opens a window where both requests pass their checks. The atomic GETDEL
    that follows is what closes it: of two double-clicks, only one may go on and connect."""
    import asyncio

    ticket = await _park()
    connected: list[str] = []

    async def fake_connect(*args, **kwargs):
        connected.append(kwargs["page"]["id"])
        return "facebook", "Page"

    class _Http:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return object()

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mo, "_connect_page", fake_connect)
    monkeypatch.setattr(mo.httpx, "AsyncClient", lambda *a, **k: _Http())
    monkeypatch.setattr(mo, "_graph_json", lambda *a, **k: {"data": [{"id": "111", "name": "A"}]})
    monkeypatch.setattr(mo, "_meta_graph_error", lambda *a, **k: None)
    monkeypatch.setattr("app.core.db.bind_tenant", noop)

    results = await asyncio.gather(
        _choose(ticket, "111"), _choose(ticket, "111"), return_exceptions=True
    )

    assert len(connected) == 1, "the same ticket connected a channel twice"
    assert sum(isinstance(r, ValidationError) for r in results) == 1
    assert sum(isinstance(r, dict) for r in results) == 1


def test_the_page_id_must_be_numeric() -> None:
    with pytest.raises(ValueError):
        mo.MetaOAuthPageChoiceIn(ticket="t" * 24, page_id="1; DROP TABLE")


def test_the_pause_carries_the_ticket_and_the_choices() -> None:
    pause = mo.PageChoiceRequired("tick", [{"id": "1", "name": "A"}])
    assert pause.ticket == "tick" and pause.choices == [{"id": "1", "name": "A"}]


def test_the_popup_asks_to_pick_instead_of_showing_an_error() -> None:
    html = mo._popup_html(
        {"type": "META_OAUTH_RESULT", "choose": {"ticket": "t" * 20, "pages": []}},
        "https://fihrist.world",
    )
    assert "اختر الصفحة" in html
    assert "تعذر إتمام الربط" not in html


# --- the whole callback path, up to the pause ------------------------------------------------


class _NoWrites:
    """A session that fails the test if the connect writes anything before the owner chose."""

    def __getattr__(self, name):
        raise AssertionError(f"the connect touched the database ({name}) before a Page was chosen")


def _graph(pages, calls):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "/oauth/access_token" in url:
            return httpx.Response(200, json={"access_token": USER_TOKEN})
        if "/me/permissions" in url:
            from app.applications.apparel.modules.customers.meta_scopes import FACEBOOK_SCOPES

            names = [s for s in FACEBOOK_SCOPES.split(",") if s]
            return httpx.Response(
                200, json={"data": [{"permission": n, "status": "granted"} for n in names]}
            )
        if "/me/accounts" in url:
            return httpx.Response(200, json={"data": pages})
        return httpx.Response(404, json={"error": {"message": "unexpected " + url}})

    return handler


async def _run_callback(monkeypatch, pages, calls):
    """Run the callback's connect against a faked Meta; `calls` collects every URL it hit."""
    import httpx

    from app.core import db as dbmod

    real = httpx.AsyncClient

    def client(**kw):
        kw.pop("transport", None)
        return real(transport=httpx.MockTransport(_graph(pages, calls)), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(mo, "_meta_config", lambda: ("app", "secret", "https://x/cb", ""))

    async def no_bind(session, tenant_id):
        return None

    monkeypatch.setattr(dbmod, "bind_tenant", no_bind)
    state = {"provider": "facebook", "tenant_id": str(TENANT), "sub": USER}
    return await mo._meta_exchange_and_connect(_NoWrites(), "code", state)


async def test_several_pages_pause_the_connect_before_anything_is_stored(
    redis, monkeypatch
) -> None:
    calls: list[str] = []
    with pytest.raises(mo.PageChoiceRequired) as pause:
        await _run_callback(monkeypatch, PAGES, calls)
    assert [c["id"] for c in pause.value.choices] == ["111", "222"]
    parked = await mo._take_page_choice(pause.value.ticket)
    assert parked["secrets"]["user_token"] == USER_TOKEN
    assert parked["user_id"] == USER and parked["provider"] == "facebook"
    assert parked["page_ids"] == ["111", "222"]


async def test_the_pause_never_subscribes_a_page_to_the_webhook(redis, monkeypatch) -> None:
    calls: list[str] = []
    with pytest.raises(mo.PageChoiceRequired):
        await _run_callback(monkeypatch, PAGES, calls)
    assert calls, "the faked Meta was never reached"
    assert not any("subscribed_apps" in url for url in calls)


async def test_a_single_page_connects_straight_away_without_asking(redis, monkeypatch) -> None:
    """One Page is not a choice: it goes to the connect step, exactly as before."""
    seen: dict = {}

    async def fake_connect(session, http, **kw):
        seen.update(kw)
        return "facebook", "Shop One"

    monkeypatch.setattr(mo, "_connect_page", fake_connect)
    calls: list[str] = []
    result = await _run_callback(monkeypatch, PAGES[:1], calls)
    assert result == ("facebook", "Shop One")
    assert seen["page"]["id"] == "111"
    assert seen["user_token"] == USER_TOKEN
    assert await redis.keys("meta_oauth:page_choice:*") == []


async def test_the_chosen_page_is_the_one_connected(redis, monkeypatch) -> None:
    """Choosing page 222 connects 222 — not the first one."""
    import httpx

    ticket = await _park(page_ids=["111", "222"])
    seen: dict = {}

    async def fake_connect(session, http, **kw):
        seen.update(kw)
        return "facebook", kw["page"]["name"]

    monkeypatch.setattr(mo, "_connect_page", fake_connect)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(_graph(PAGES, [])),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    )

    async def no_bind(session, tenant_id):
        return None

    from app.core import db as dbmod

    monkeypatch.setattr(dbmod, "bind_tenant", no_bind)
    out = await _choose(ticket, "222")
    assert out == {"connected": "facebook:Shop Two"}
    assert seen["page"]["id"] == "222"
    assert seen["user_token"] == USER_TOKEN
    assert seen["expires_in"] == 5_183_944
