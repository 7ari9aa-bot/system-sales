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

from app.applications.apparel.modules.customers import meta_oauth
from app.applications.apparel.modules.customers.meta_scopes import (
    FACEBOOK_PAGE_SCOPES,
    FACEBOOK_SCOPES,
    MESSENGER_SCOPES,
    PAGES_BASE_SCOPES,
)


def _scopes(scope_string: str) -> set[str]:
    return {part.strip() for part in scope_string.split(",") if part.strip()}


def test_managing_a_page_never_asks_for_the_inbox():
    """Page management and Messenger are two functions with two permission sets.

    Meta delivers both over one Page object, but chat always lands on the Messenger capability
    (gateway/meta_page_events.py sends every `messaging` entry there), so the Page dialog must not
    make a store that only posts and moderates hand over its customers' messages.
    """
    facebook = _scopes(FACEBOOK_SCOPES)

    assert "pages_messaging" not in facebook
    assert set(FACEBOOK_PAGE_SCOPES) <= facebook
    assert _scopes(PAGES_BASE_SCOPES) <= facebook


def test_the_private_reply_is_the_one_facebook_feature_that_needs_the_inbox_grant():
    """A private reply is a Messenger message, so it is declared as its own capability.

    It is reported as `needs_permission` until the Messenger connection on the same Page grants
    `pages_messaging`, instead of being smuggled into the Page dialog.
    """
    from app.applications.apparel.modules.customers.capability_states import _CAPABILITIES
    from app.applications.apparel.modules.customers.meta_scopes import (
        FACEBOOK_PRIVATE_REPLY_SCOPES,
        missing_private_reply_scopes,
    )

    assert FACEBOOK_PRIVATE_REPLY_SCOPES == ("pages_messaging",)
    assert missing_private_reply_scopes(["pages_manage_posts"]) == ["pages_messaging"]
    assert missing_private_reply_scopes(["pages_messaging"]) == []

    declared = {c["key"]: c for c in _CAPABILITIES["facebook"]}
    assert declared["private_reply"]["scopes"] == ("pages_messaging",)


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

    # Chat needs MESSAGING (or MANAGE, which implies it); page management needs MANAGE. Neither
    # offers a Page whose only task is advertising, and neither is judged by the other's rule.
    for provider in ("messenger", "instagram"):
        assert [p["id"] for p in meta_oauth._messaging_pages(pages, provider)] == ["1", "2", "3"]
    assert [p["id"] for p in meta_oauth._messaging_pages(pages, "facebook")] == ["2", "3"]


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ManyResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, existing=None, others=()) -> None:
        self.existing = existing
        # Other channel rows of the same workspace (e.g. Messenger already on the Page).
        self.others = list(others)
        self.added: list[object] = []
        self.flushed = False

    async def execute(self, stmt):
        if "other" in str(getattr(stmt, "_where_criteria", "")) or "!=" in str(stmt):
            return _ManyResult(self.others)
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
        "app.platform.billing.service.EntitlementService.ensure_channel_allowed",
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


@pytest.mark.asyncio
async def test_a_failed_facebook_save_leaves_messengers_subscription_alone(monkeypatch):
    """Messenger already runs on this Page. Facebook then failing to save must NOT take the app
    off the Page: they share one subscription, and removing it would cut Messenger's webhooks."""
    unsubscribed: list[dict] = []

    async def subscribe(*args, **kwargs):
        return None

    async def unsubscribe(http, *, page_id, page_token):
        unsubscribed.append({"page_id": page_id})
        return True

    monkeypatch.setattr(meta_oauth, "_subscribe_page_to_app", subscribe)
    monkeypatch.setattr(meta_oauth, "_unsubscribe_page_from_app", unsubscribe)
    monkeypatch.setattr(meta_oauth, "verify_channel_credentials", _verified)

    messenger_row = SimpleNamespace(provider="messenger", config={"account_id": "page-1"})
    session = _Session(existing=None, others=[messenger_row])

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

    assert unsubscribed == []


async def _verified(provider, credentials, config, client=None):
    return SimpleNamespace(display_name="صفحة", identity_config={"page_id": "page-1"})
