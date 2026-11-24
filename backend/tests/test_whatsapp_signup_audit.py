"""One-click WhatsApp connect leaves the same audit row the manual connect does (W10).

The manual connect writes `integration.connected`; the Embedded Signup route redirects the very same
webhook traffic and used to leave no trace of who bound which number. The row carries identity only.
"""

from __future__ import annotations

import types
import uuid

import pytest

from app.modules.customers import meta_whatsapp_signup as signup
from app.modules.platform.services import audit as audit_module

TENANT = uuid.uuid4()
USER = uuid.uuid4()
SECRET_TOKEN = "EAAB-super-secret-token"
SECRET_CODE = "AUTHCODE-secret"


class _Result:
    def scalar_one_or_none(self):
        return None


class _Session:
    def __init__(self) -> None:
        self.added: list = []

    async def execute(self, *_a, **_k):
        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.fixture
def harness(monkeypatch):
    audit_calls: list[tuple[tuple, dict]] = []

    async def fake_audit(*args, **kwargs):
        audit_calls.append((args, kwargs))

    monkeypatch.setattr(audit_module.AuditService, "write", staticmethod(fake_audit))
    monkeypatch.setattr(signup, "_whatsapp_config", lambda: ("app", "secret", "config"))

    async def ok(*_a, **_k):
        return None

    async def exchange(*_a, **_k):
        return SECRET_TOKEN, None

    async def register(*_a, **_k):
        return "123456"

    async def display(*_a, **_k):
        return "Shop"

    async def pin(*_a, **_k):
        return None

    async def verify(*_a, **_k):
        return types.SimpleNamespace(identity_config={"account_id": "2002"}, display_name="Shop")

    async def platform_facts(*_a, **_k):
        # A Cloud API number: the connect path registers it, which is what this test stubs above.
        # Meta's own answer about the number is a separate read, stubbed so the flow never leaves
        # the process.
        return {"is_on_biz_app": False, "platform_type": "CLOUD_API"}

    monkeypatch.setattr(signup, "_exchange_code_for_token", exchange)
    monkeypatch.setattr(signup, "_verify_phone_belongs_to_waba", ok)
    monkeypatch.setattr(signup, "_phone_display_name", display)
    monkeypatch.setattr(signup, "_register_phone_number", register)
    monkeypatch.setattr(signup, "_subscribe_app_to_waba", ok)
    monkeypatch.setattr(signup, "_take_pending_pin", pin)
    monkeypatch.setattr(signup, "_number_platform_facts", platform_facts)
    monkeypatch.setattr(
        "app.modules.platform.integration_verifier.verify_channel_credentials", verify
    )

    class _Entitlements:
        @staticmethod
        async def ensure_channel_allowed(*_a, **_k):
            return None

    monkeypatch.setattr("app.modules.billing.service.EntitlementService", _Entitlements)
    return audit_calls


def _ctx():
    return types.SimpleNamespace(tenant_id=TENANT, user=types.SimpleNamespace(id=USER))


def _body():
    return signup.WhatsAppSignupCompleteBody(
        code=SECRET_CODE, waba_id="1001", phone_number_id="2002"
    )


async def test_connecting_by_popup_writes_the_audit_row(harness):
    await signup.whatsapp_signup_complete(_body(), _Session(), _ctx())

    assert len(harness) == 1
    args, kwargs = harness[0]
    assert args[1] == TENANT
    assert args[2] == USER
    assert args[3] == "integration.connected"
    assert args[4] == "integration"
    after = kwargs["after"]
    assert after["provider"] == "whatsapp"
    assert after["via"] == "embedded_signup"
    assert after["is_new"] is True
    assert after["phone_number_id"] == "2002"
    assert after["waba_id"] == "1001"


async def test_the_audit_row_never_carries_a_credential(harness):
    await signup.whatsapp_signup_complete(_body(), _Session(), _ctx())

    dumped = repr(harness)
    for secret in (SECRET_TOKEN, SECRET_CODE, "123456", "secret"):
        assert secret not in dumped
