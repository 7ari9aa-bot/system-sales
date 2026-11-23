"""A connect that is refused locally must not have touched Meta; one that fails after must undo it.

`_connect_page` used to subscribe the Page at Meta first and only then ask whether the plan allows
the channel or whether it was disabled for good, which left a subscription at Meta with no
connection behind it. These tests drive the real function with a recording Graph and fakes for the
database, and check the ORDER of effects.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.modules.customers import meta_oauth

PAGE = {"id": "p1", "name": "Page", "access_token": "tok", "tasks": ["MESSAGING"]}
TENANT = uuid.uuid4()


class _Result:
    def __init__(self, value=None, many=()):
        self.value = value
        self.many = list(many)

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.many)


class _Session:
    def __init__(self, existing=None, *, fail_flush=False, siblings=()):
        self.existing = existing
        self.fail_flush = fail_flush
        self.siblings = list(siblings)
        self.calls = 0

    async def execute(self, statement):
        self.calls += 1
        if "providers" in str(statement) or "provider !=" in str(statement) or self.calls > 1:
            return _Result(many=self.siblings)
        return _Result(self.existing)

    def add(self, row):
        self.row = row

    async def flush(self):
        if self.fail_flush:
            raise RuntimeError("db down")


@pytest.fixture
def world(monkeypatch):
    events: list[str] = []

    async def verify(provider, credentials, config, client=None):
        events.append("verify")
        return SimpleNamespace(display_name="Page", identity_config={"page_id": "p1"})

    async def subscribe(http, *, page_id, page_token, provider="messenger"):
        events.append("subscribe")
        return True

    async def entitlement(session, tenant_id, provider):
        events.append("entitlement")

    async def undo(session, http, **kw):
        events.append("undo")

    monkeypatch.setattr(meta_oauth, "verify_channel_credentials", verify)
    monkeypatch.setattr(meta_oauth, "_subscribe_page_to_app", subscribe)
    monkeypatch.setattr(meta_oauth, "_undo_page_subscription", undo)
    monkeypatch.setattr(
        "app.modules.billing.service.EntitlementService.ensure_channel_allowed", entitlement
    )
    monkeypatch.setattr(
        "app.modules.customers.routers.integrations._activate_verified_channel", lambda row: None
    )
    return events


async def _connect(session):
    return await meta_oauth._connect_page(
        session,
        object(),
        page=dict(PAGE),
        provider="messenger",
        tenant_id=TENANT,
        user_token="u",
        expires_in=3600,
        granted=["pages_messaging"],
        config_id="",
    )


async def test_the_plan_is_checked_before_meta_is_touched(world):
    await _connect(_Session())
    assert world.index("entitlement") < world.index("subscribe")


async def test_a_plan_refusal_leaves_meta_untouched(world, monkeypatch):
    async def refuse(session, tenant_id, provider):
        world.append("entitlement")
        raise ValidationError("plan does not include this channel")

    monkeypatch.setattr(
        "app.modules.billing.service.EntitlementService.ensure_channel_allowed", refuse
    )
    with pytest.raises(ValidationError):
        await _connect(_Session())
    assert "subscribe" not in world and "undo" not in world


async def test_a_permanently_disabled_channel_leaves_meta_untouched(world):
    disabled = SimpleNamespace(status="disabled")
    with pytest.raises(ValidationError, match="permanently disabled"):
        await _connect(_Session(existing=disabled))
    assert "subscribe" not in world


async def test_a_reconnect_does_not_ask_the_plan_again(world):
    existing = SimpleNamespace(status="active", config={}, credentials=b"")
    await _connect(_Session(existing=existing))
    assert "entitlement" not in world and "subscribe" in world


async def test_a_failed_save_after_subscribing_takes_the_subscription_back(world):
    with pytest.raises(RuntimeError, match="db down"):
        await _connect(_Session(fail_flush=True))
    assert world[-1] == "undo"


async def test_a_failed_save_never_undoes_a_subscription_that_was_already_there(world, monkeypatch):
    async def already(http, *, page_id, page_token, provider="messenger"):
        world.append("subscribe")
        return False  # nothing new was added by this connect

    monkeypatch.setattr(meta_oauth, "_subscribe_page_to_app", already)
    with pytest.raises(RuntimeError):
        await _connect(_Session(fail_flush=True))
    assert "undo" not in world


async def test_a_successful_connect_never_undoes_anything(world):
    provider, _name = await _connect(_Session())
    assert provider == "messenger" and "undo" not in world


async def test_the_rollback_keeps_what_a_sibling_channel_needs(monkeypatch):
    seen = {}

    async def unsubscribe(http, *, page_id, page_token, sibling_providers):
        seen.update(page=page_id, siblings=sibling_providers)
        return {}

    monkeypatch.setattr("app.modules.customers.meta_unsubscribe.unsubscribe_page", unsubscribe)
    monkeypatch.setattr(meta_oauth, "decrypt_credentials_dict", lambda c: {})
    sibling = SimpleNamespace(provider="facebook", config={"page_id": "p1"}, credentials=b"")
    other_page = SimpleNamespace(provider="instagram", config={"account_id": "zz"}, credentials=b"")
    session = _Session(siblings=[sibling, other_page])
    await meta_oauth._undo_page_subscription(
        session, object(), page=dict(PAGE), provider="messenger", tenant_id=TENANT, token="tok"
    )
    assert seen == {"page": "p1", "siblings": ["facebook"]}


async def test_a_rollback_that_fails_never_hides_the_original_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("meta down")

    monkeypatch.setattr("app.modules.customers.meta_unsubscribe.unsubscribe_page", boom)

    async def flag(*a, **k):
        return None

    monkeypatch.setattr(meta_oauth, "_flag", flag)
    await meta_oauth._undo_page_subscription(
        _Session(), object(), page=dict(PAGE), provider="messenger", tenant_id=TENANT, token="t"
    )
