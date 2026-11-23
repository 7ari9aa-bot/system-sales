"""A capability asks for its own permissions, and is refused before Meta is touched.

Two separate faults, both invisible until a real Page is connected:
  * the Facebook channel reused Messenger's scope list, so managing a Page forced the owner to
    hand over their inbox (`pages_messaging`), a permission that flow never uses;
  * the Page filter offered any Page with MESSAGING, so the Facebook flow could connect a Page
    where the operator cannot post at all;
  * and the entitlement / disabled checks ran AFTER the Page was subscribed, so a refused
    connect had already changed Meta.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.customers import meta_oauth
from app.modules.customers.meta_scopes import (
    FACEBOOK_PAGE_SCOPES,
    FACEBOOK_SCOPES,
    MESSENGER_SCOPES,
    PAGES_BASE_SCOPES,
)


def _scopes(scope_string: str) -> set[str]:
    return {part.strip() for part in scope_string.split(",") if part.strip()}


def test_the_facebook_channel_keeps_the_inbox_grant_because_it_really_chats():
    """The audit called this "linking Page management forces Messenger permissions".

    Measured against the code: `FacebookPageAdapter` is Messenger's protocol under the Page's name
    (gateway/facebook.py, channel = "facebook"), so this connection receives and answers the
    Page's DMs. Removing `pages_messaging` would leave it unable to reply to anyone, so the grant
    stays and the reason is now written next to it in meta_scopes.py.
    """
    facebook = _scopes(FACEBOOK_SCOPES)

    assert "pages_messaging" in facebook
    assert set(FACEBOOK_PAGE_SCOPES) <= facebook
    assert _scopes(PAGES_BASE_SCOPES) <= facebook


def test_messenger_still_asks_for_the_inbox_and_nothing_more():
    messenger = _scopes(MESSENGER_SCOPES)

    assert "pages_messaging" in messenger
    assert _scopes(PAGES_BASE_SCOPES) <= messenger
    assert not set(FACEBOOK_PAGE_SCOPES) & messenger, (
        "chat must not ask to publish or read insights"
    )


def test_a_page_the_operator_has_no_task_on_is_never_offered():
    pages = [
        {"id": "1", "tasks": ["MESSAGING"]},
        {"id": "2", "tasks": ["MANAGE"]},
        {"id": "3"},
        {"id": "4", "tasks": ["ADVERTISE"]},
    ]

    for provider in ("facebook", "messenger", "instagram"):
        assert [p["id"] for p in meta_oauth._messaging_pages(pages, provider)] == ["1", "2", "3"]


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.flushed = False

    async def execute(self, stmt):
        return _Result(self.existing)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


def _page() -> dict:
    return {"id": "page-1", "name": "صفحة", "access_token": "page-token", "tasks": ["MANAGE"]}


@pytest.mark.asyncio
async def test_a_refused_entitlement_never_touches_meta(monkeypatch):
    calls: list[str] = []

    async def ensure_channel_allowed(session, tenant_id, provider):
        calls.append("entitlement")
        raise meta_oauth.ValidationError("no room on this plan")

    async def subscribe(*args, **kwargs):
        calls.append("subscribe")

    monkeypatch.setattr(
        "app.modules.billing.service.EntitlementService.ensure_channel_allowed",
        staticmethod(ensure_channel_allowed),
    )
    monkeypatch.setattr(meta_oauth, "_subscribe_page_to_app", subscribe)

    session = _Session(existing=None)
    with pytest.raises(meta_oauth.ValidationError):
        await meta_oauth._connect_page(
            session,
            http=None,
            page=_page(),
            provider="facebook",
            tenant_id=uuid.uuid4(),
            user_token="user-token",
            expires_in=None,
            granted=["pages_show_list"],
            config_id="",
        )

    assert calls == ["entitlement"], "Meta was changed before the local refusal"


@pytest.mark.asyncio
async def test_a_disabled_channel_is_refused_before_meta(monkeypatch):
    calls: list[str] = []

    async def subscribe(*args, **kwargs):
        calls.append("subscribe")

    monkeypatch.setattr(meta_oauth, "_subscribe_page_to_app", subscribe)

    session = _Session(existing=SimpleNamespace(status="disabled"))
    with pytest.raises(meta_oauth.ValidationError):
        await meta_oauth._connect_page(
            session,
            http=None,
            page=_page(),
            provider="facebook",
            tenant_id=uuid.uuid4(),
            user_token="user-token",
            expires_in=None,
            granted=[],
            config_id="",
        )

    assert calls == []


@pytest.mark.asyncio
async def test_a_failed_first_save_takes_the_subscription_back(monkeypatch):
    unsubscribed: list[dict] = []

    async def subscribe(*args, **kwargs):
        return None

    async def unsubscribe(http, *, page_id, page_token):
        unsubscribed.append({"page_id": page_id, "page_token": page_token})
        return True

    monkeypatch.setattr(meta_oauth, "_subscribe_page_to_app", subscribe)
    monkeypatch.setattr(meta_oauth, "_unsubscribe_page_from_app", unsubscribe)
    monkeypatch.setattr(meta_oauth, "verify_channel_credentials", _verified)

    session = _Session(existing=None)

    async def failing_flush():
        raise RuntimeError("database went away")

    session.flush = failing_flush

    with pytest.raises(RuntimeError):
        await meta_oauth._connect_page(
            session,
            http=None,
            page=_page(),
            provider="facebook",
            tenant_id=uuid.uuid4(),
            user_token="user-token",
            expires_in=None,
            granted=[],
            config_id="",
        )

    assert unsubscribed == [{"page_id": "page-1", "page_token": "page-token"}]


async def _verified(provider, credentials, config, client=None):
    return SimpleNamespace(display_name="صفحة", identity_config={"page_id": "page-1"})
