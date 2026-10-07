"""Channel HTTP routes verify accounts and keep provider secrets private."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

from app.core.errors import ValidationError
from app.modules.platform.integration_verifier import VerifiedChannel
from app.modules.platform.models import Integration
from app.modules.platform.service import IntegrationCredentialsService
from tests.test_customers_http_surface import TENANT, _call


async def test_connect_persists_only_after_provider_verification(monkeypatch) -> None:  # noqa: ANN001
    async def allow_channel(_session, _tenant_id, _provider) -> None:
        return None

    async def verify(provider, credentials, config) -> VerifiedChannel:  # noqa: ANN001
        assert provider == "whatsapp"
        assert credentials == {"access_token": "submitted-secret"}
        assert config == {"phone_number_id": "123456789"}
        return VerifiedChannel({"phone_number_id": "123456789"}, "Shop")

    monkeypatch.setattr(
        "app.modules.customers.router.EntitlementService.ensure_channel_allowed",
        staticmethod(allow_channel),
    )
    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", verify)

    response, _session = await _call(
        "POST",
        "/api/v1/integrations/connect",
        permissions={"settings:write"},
        body={
            "provider": "whatsapp",
            "credentials": {"access_token": "submitted-secret"},
            "config": {"phone_number_id": "123456789"},
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "active"
    assert result["credentials_verified"] is True
    assert result["display_name"] == "Shop"
    assert "submitted-secret" not in response.text


async def test_telegram_connect_registers_webhook_with_server_routing_key(monkeypatch) -> None:  # noqa: ANN001
    routing_key = "telegram_routing_key_abcdefghijklmnopqrstuvwxyz"
    registered_urls: list[str] = []

    async def allow_channel(_session, _tenant_id, _provider) -> None:
        return None

    async def verify(provider, credentials, config) -> VerifiedChannel:  # noqa: ANN001
        assert provider == "telegram"
        assert credentials["bot_token"] == "123456:valid-bot-token"
        assert config == {}
        return VerifiedChannel({"bot_id": "456789", "public_key": routing_key}, "sales_bot")

    async def configure(credentials, webhook_url) -> None:  # noqa: ANN001
        assert credentials["bot_token"] == "123456:valid-bot-token"
        registered_urls.append(webhook_url)

    monkeypatch.setattr(
        "app.modules.customers.router.EntitlementService.ensure_channel_allowed",
        staticmethod(allow_channel),
    )
    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", verify)
    monkeypatch.setattr("app.modules.customers.router.configure_telegram_webhook", configure)
    monkeypatch.setattr(
        "app.modules.customers.router._telegram_webhook_url",
        lambda key: f"https://api.example.test/api/v1/webhooks/telegram?tenant_key={key}",
    )

    response, _session = await _call(
        "POST",
        "/api/v1/integrations/connect",
        permissions={"settings:write"},
        body={"provider": "telegram", "credentials": {"bot_token": "123456:valid-bot-token"}},
    )

    assert response.status_code == 201, response.text
    assert response.json()["credentials_verified"] is True
    assert len(registered_urls) == 1
    parsed = urlparse(registered_urls[0])
    assert parsed.path == "/api/v1/webhooks/telegram"
    assert parse_qs(parsed.query) == {"tenant_key": [routing_key]}


async def test_telegram_reconnect_keeps_routing_key_and_updates_bot_identity(monkeypatch) -> None:  # noqa: ANN001
    routing_key = "telegram_routing_key_abcdefghijklmnopqrstuvwxyz"
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        provider="telegram",
        kind="channel",
        status="active",
        config={"bot_id": "111111", "public_key": routing_key},
        credentials={"ciphertext": "old-encrypted-token"},
    )
    registered_urls: list[str] = []

    async def verify(provider, credentials, config) -> VerifiedChannel:  # noqa: ANN001
        assert provider == "telegram"
        assert config["public_key"] == routing_key
        return VerifiedChannel({"bot_id": "222222", "public_key": routing_key}, "sales_bot")

    async def configure(_credentials, webhook_url) -> None:  # noqa: ANN001
        registered_urls.append(webhook_url)

    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", verify)
    monkeypatch.setattr("app.modules.customers.router.configure_telegram_webhook", configure)
    monkeypatch.setattr(
        "app.modules.customers.router._telegram_webhook_url",
        lambda key: f"https://api.example.test/api/v1/webhooks/telegram?tenant_key={key}",
    )

    response, _session = await _call(
        "POST",
        "/api/v1/integrations/connect",
        rows=[row],
        permissions={"settings:write"},
        body={"provider": "telegram", "credentials": {"bot_token": "123456:new-valid-token"}},
    )

    assert response.status_code == 201, response.text
    assert row.config["bot_id"] == "222222"
    assert row.config["public_key"] == routing_key
    assert len(registered_urls) == 1
    assert parse_qs(urlparse(registered_urls[0]).query) == {"tenant_key": [routing_key]}


def test_telegram_callback_uses_only_the_configured_canonical_origin(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from app.modules.customers.router import _telegram_webhook_url

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(api_public_base_url="https://api.example.test/"),
    )
    assert _telegram_webhook_url("routing-key") == (
        "https://api.example.test/api/v1/webhooks/telegram?tenant_key=routing-key"
    )


def test_telegram_callback_rejects_noncanonical_or_insecure_origins(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from app.core.errors import ExternalProviderError
    from app.modules.customers.router import _telegram_webhook_url

    for origin in (
        "http://api.example.test",
        "https://attacker.example.test/path",
        "https://user@api.example.test",
        "https://api.example.test?redirect=evil",
    ):
        monkeypatch.setattr(
            "app.core.config.get_settings",
            lambda origin=origin: SimpleNamespace(api_public_base_url=origin),
        )
        try:
            _telegram_webhook_url("routing-key")
        except ExternalProviderError as error:
            assert "canonical HTTPS" in error.message
        else:
            raise AssertionError(f"noncanonical webhook origin was accepted: {origin}")


def test_meta_webhook_callbacks_use_the_configured_public_api_origin(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from app.modules.customers.router import _provider_webhook_url

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(api_public_base_url="https://api.example.test"),
    )
    assert _provider_webhook_url("whatsapp") == (
        "https://api.example.test/api/v1/webhooks/whatsapp"
    )
    assert _provider_webhook_url("instagram") == (
        "https://api.example.test/api/v1/webhooks/instagram"
    )
    assert _provider_webhook_url("messenger") == (
        "https://api.example.test/api/v1/webhooks/messenger"
    )
    assert _provider_webhook_url("webchat") is None


async def test_failed_provider_verification_does_not_create_an_active_channel(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def allow_channel(_session, _tenant_id, _provider) -> None:
        return None

    async def reject(_provider, _credentials, _config):  # noqa: ANN001
        raise ValidationError("The provider rejected these credentials.")

    monkeypatch.setattr(
        "app.modules.customers.router.EntitlementService.ensure_channel_allowed",
        staticmethod(allow_channel),
    )
    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", reject)

    response, _session = await _call(
        "POST",
        "/api/v1/integrations/connect",
        permissions={"settings:write"},
        body={
            "provider": "whatsapp",
            "credentials": {"access_token": "invalid-secret"},
            "config": {"phone_number_id": "123456789"},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "The provider rejected these credentials."
    assert "invalid-secret" not in response.text


async def test_legacy_endpoint_cannot_claim_a_channel_is_active() -> None:
    response, _session = await _call(
        "POST",
        "/api/v1/integrations",
        permissions={"settings:write"},
        body={
            "provider": "whatsapp",
            "kind": "channel",
            "status": "active",
            "credentials": {"access_token": "not-verified"},
            "config": {"phone_number_id": "123456789"},
        },
    )

    assert response.status_code == 400
    assert "/integrations/connect" in response.json()["error"]["message"]


async def test_verify_marks_revoked_saved_credentials_for_reauthentication(
    monkeypatch,
) -> None:  # noqa: ANN001
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        provider="whatsapp",
        kind="channel",
        status="active",
        config={
            "phone_number_id": "123456789",
            "_connection": {"verified_at": "2026-01-01T00:00:00+00:00", "display_name": "Shop"},
        },
        credentials={"ciphertext": "not-a-plaintext-token"},
    )

    async def decrypt(_session, integration) -> dict:  # noqa: ANN001
        assert integration is row
        return {"access_token": "old-secret"}

    async def reject(_provider, _credentials, _config):  # noqa: ANN001
        raise ValidationError("The provider rejected these credentials.")

    monkeypatch.setattr(IntegrationCredentialsService, "decrypt", staticmethod(decrypt))
    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", reject)

    response, _session = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/verify",
        rows=[row],
        permissions={"settings:write"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "reauth_required"
    assert result["credentials_verified"] is False
    assert "old-secret" not in response.text
    assert "ciphertext" not in response.text
    assert row.status == "reauth_required"


async def test_verify_success_returns_identity_without_credentials(monkeypatch) -> None:  # noqa: ANN001
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        provider="messenger",
        kind="channel",
        status="reauth_required",
        config={},
        credentials={"ciphertext": "encrypted"},
    )

    async def decrypt(_session, integration) -> dict:  # noqa: ANN001
        assert integration is row
        return {"api_key": "page-secret"}

    async def verify(provider, credentials, config) -> VerifiedChannel:  # noqa: ANN001
        assert provider == "messenger"
        assert credentials == {"api_key": "page-secret"}
        assert config == {}
        return VerifiedChannel({"account_id": "345678901"}, "Page")

    monkeypatch.setattr(IntegrationCredentialsService, "decrypt", staticmethod(decrypt))
    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", verify)

    response, _session = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/verify",
        rows=[row],
        permissions={"settings:write"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "active"
    assert result["credentials_verified"] is True
    assert result["display_name"] == "Page"
    assert "page-secret" not in response.text


# ---------------------------------------------------------------------------
# Package 2.1 — the disconnect surface + the audit trail for connect/verify.
#
# The §145 lifecycle had a "disconnected" state nothing could drive: a channel
# could never be detached from the settings surface at all, and connecting or
# re-verifying a channel left no audit entry. These tests pin the route the
# hardening added (confirmation-gated, state-machine-fail-closed, audited) and
# the §66 audit rows the connect/verify paths now write.
# ---------------------------------------------------------------------------


def _channel_row(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "provider": "whatsapp",
        "kind": "channel",
        "status": "active",
        "config": {"phone_number_id": "123456789"},
        "credentials": {"ciphertext": "encrypted"},
    }
    defaults.update(overrides)
    return Integration(**defaults)


async def test_disconnect_requires_explicit_confirmation() -> None:
    """A stray click or replayed request must not cut live provider traffic:
    the body has to carry confirm=true, and a defaulted body changes nothing."""
    row = _channel_row()

    response, _session = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/disconnect",
        rows=[row],
        permissions={"settings:write"},
        body={"confirm": False},
    )

    assert response.status_code == 400, response.text
    assert "confirm" in response.json()["error"]["message"]
    assert row.status == "active"


async def test_disconnect_is_gated_by_settings_write() -> None:
    row = _channel_row()

    response, _session = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/disconnect",
        rows=[row],
        permissions=set(),
        body={"confirm": True},
    )

    assert response.status_code == 403, response.text


async def test_disconnect_refuses_states_without_provider_traffic() -> None:
    """Fail-closed on the §145 machine: only active|restricted receive
    provider webhooks, so only they may disconnect."""
    row = _channel_row(status="reauth_required")

    response, _session = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/disconnect",
        rows=[row],
        permissions={"settings:write"},
        body={"confirm": True},
    )

    assert response.status_code == 400, response.text
    assert "active" in response.json()["error"]["message"]


async def test_disconnect_is_listed_in_the_gate_inventory() -> None:
    """The route must stay in the customers-surface gate inventory: one
    permission code (settings:write) and the route-count pin bumped with it."""
    from tests.test_customers_http_surface import GATED_WRITES

    assert (
        GATED_WRITES["POST /integrations/{integration_id}/disconnect"]
        == "settings:write"
    )


def _settings_ctx(db, tenant_ctx) -> TenantContext:
    from app.modules.identity.deps import AuthedUser, TenantContext

    return TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code=tenant_ctx.role.code,
            is_active=True,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code=tenant_ctx.role.code,
        permission_codes={"settings:write"},
    )


async def test_disconnect_moves_active_to_disconnected_and_audits(db, tenant_ctx) -> None:
    from sqlalchemy import func, select

    from app.modules.customers.schemas import IntegrationDisconnectBody
    from app.modules.customers.router import disconnect_integration
    from app.modules.platform.models import AuditLog

    row = _channel_row(tenant_id=tenant_ctx.tenant_id)
    db.add(row)
    await db.flush()
    ctx = _settings_ctx(db, tenant_ctx)

    result = await disconnect_integration(
        row.id, IntegrationDisconnectBody(confirm=True), ctx
    )

    assert result["status"] == "disconnected"
    audit = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "integration.disconnected",
                AuditLog.resource_id == str(row.id),
            )
        )
    ).scalar_one()
    assert audit == 1

    # Idempotent: a repeated confirmed disconnect is a no-op, not a second
    # audit row and not an illegal self-transition.
    result = await disconnect_integration(
        row.id, IntegrationDisconnectBody(confirm=True), ctx
    )
    assert result["status"] == "disconnected"
    audit = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "integration.disconnected",
                AuditLog.resource_id == str(row.id),
            )
        )
    ).scalar_one()
    assert audit == 1


async def test_connect_writes_an_audit_entry_without_secrets(
    db, tenant_ctx, monkeypatch
) -> None:  # noqa: ANN001
    from sqlalchemy import select

    from app.modules.customers.schemas import IntegrationConnectBody
    from app.modules.customers.router import connect_integration
    from app.modules.platform.models import AuditLog

    async def allow_channel(_session, _tenant_id, _provider) -> None:
        return None

    async def verify(_provider, _credentials, _config) -> VerifiedChannel:
        return VerifiedChannel({"phone_number_id": "123456789"}, "Shop")

    monkeypatch.setattr(
        "app.modules.customers.router.EntitlementService.ensure_channel_allowed",
        staticmethod(allow_channel),
    )
    monkeypatch.setattr(
        "app.modules.customers.router.verify_channel_credentials", verify
    )
    ctx = _settings_ctx(db, tenant_ctx)

    result = await connect_integration(
        IntegrationConnectBody(
            provider="whatsapp",
            credentials={"access_token": "submitted-secret"},
            config={"phone_number_id": "123456789"},
        ),
        ctx,
    )

    assert result["credentials_verified"] is True
    audits = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "integration.connected",
                    AuditLog.resource_id == result["id"],
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    # The audit row carries identity metadata only — never the credential.
    assert "submitted-secret" not in str(audits[0].after)


async def test_verification_failure_demotes_the_channel_and_audits(
    db, tenant_ctx, monkeypatch
) -> None:  # noqa: ANN001
    from sqlalchemy import func, select

    from app.modules.customers.router import verify_integration
    from app.modules.platform.models import AuditLog

    row = _channel_row(tenant_id=tenant_ctx.tenant_id)
    db.add(row)
    await db.flush()

    async def decrypt(_session, integration) -> dict:
        return {"access_token": "old-secret"}

    async def reject(_provider, _credentials, _config) -> None:
        raise ValidationError("The provider rejected these credentials.")

    monkeypatch.setattr(IntegrationCredentialsService, "decrypt", staticmethod(decrypt))
    monkeypatch.setattr(
        "app.modules.customers.router.verify_channel_credentials", reject
    )
    ctx = _settings_ctx(db, tenant_ctx)

    result = await verify_integration(row.id, ctx)

    assert result["status"] == "reauth_required"
    audit = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "integration.verification_failed",
                AuditLog.resource_id == str(row.id),
            )
        )
    ).scalar_one()
    assert audit == 1
    assert row.status == "reauth_required"
