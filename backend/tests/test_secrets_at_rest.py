"""§68/§69: at-rest envelope encryption for Integration.credentials.

Crypto classes run anywhere (no DB); the persistence class is DB-backed
(conftest fixtures — skips locally, runs in CI on real Postgres).
"""

from __future__ import annotations

import base64

import pytest

from app.core.secrets import (
    EnvelopeSecretStore,
    SecretDecryptionError,
    SecretKeyError,
    decrypt_credentials_dict,
    encrypt_credentials_dict,
    validate_rotation_candidate,
)


def _key(seed: bytes = b"k") -> str:
    return base64.b64encode(seed * 32).decode("ascii")


class TestEnvelopeCrypto:
    """AES-256-GCM envelope — round-trip, fallback, tamper, key ring."""

    def test_round_trip(self):
        store = EnvelopeSecretStore(_key())
        ciphertext = store.encrypt("wa-token-123")
        assert ciphertext.startswith("v1:")
        assert "wa-token-123" not in ciphertext
        result = store.decrypt(ciphertext)
        assert result.value == "wa-token-123"
        assert result.was_plaintext is False

    def test_plaintext_legacy_fallback(self):
        store = EnvelopeSecretStore(_key())
        result = store.decrypt("legacy-plain-token")
        assert result.value == "legacy-plain-token"
        assert result.was_plaintext is True

    def test_tampered_ciphertext_raises(self):
        store = EnvelopeSecretStore(_key())
        ciphertext = store.encrypt("secret")
        body = ciphertext[len("v1:") :]
        wrapped_b64, data_b64 = body.split(":")
        raw = bytearray(base64.b64decode(data_b64))
        raw[-1] ^= 0xFF  # flip one bit in the ciphertext/tag
        tampered = "v1:" + wrapped_b64 + ":" + base64.b64encode(bytes(raw)).decode()
        with pytest.raises(SecretDecryptionError):
            store.decrypt(tampered)

    def test_wrong_master_key_raises(self):
        ciphertext = EnvelopeSecretStore(_key(b"a")).encrypt("secret")
        with pytest.raises(SecretDecryptionError):
            EnvelopeSecretStore(_key(b"b")).decrypt(ciphertext)

    def test_malformed_v1_raises(self):
        store = EnvelopeSecretStore(_key())
        with pytest.raises(SecretDecryptionError):
            store.decrypt("v1:not!base64")

    def test_weak_or_malformed_master_key_rejected(self):
        with pytest.raises(SecretKeyError):
            EnvelopeSecretStore(base64.b64encode(b"short").decode())
        with pytest.raises(SecretKeyError):
            EnvelopeSecretStore("!!! not base64 !!!")

    def test_key_ring_decrypts_previous_master(self):
        old = EnvelopeSecretStore(_key(b"o"))
        ciphertext = old.encrypt("secret-under-old-key")
        ring = EnvelopeSecretStore(_key(b"n"), previous_master_keys=[_key(b"o")])
        assert ring.decrypt(ciphertext).value == "secret-under-old-key"
        # ...but new writes use the NEW key only.
        new_ciphertext = ring.encrypt("fresh")
        with pytest.raises(SecretDecryptionError):
            old.decrypt(new_ciphertext)


class TestCredentialsDict:
    """Per-value encryption over the JSONB credentials dict."""

    def test_round_trip_preserves_types(self):
        store = EnvelopeSecretStore(_key())
        original = {"token": "abc", "expires": 3600, "verified": True}
        encrypted = encrypt_credentials_dict(original, store=store)
        assert set(encrypted) == set(original)
        for value in encrypted.values():
            assert isinstance(value, str) and value.startswith("v1:")
        assert decrypt_credentials_dict(encrypted, store=store) == original

    def test_already_encrypted_values_not_double_encrypted(self):
        store = EnvelopeSecretStore(_key())
        once = encrypt_credentials_dict({"token": "abc"}, store=store)
        twice = encrypt_credentials_dict(once, store=store)
        assert twice == once

    def test_plaintext_values_pass_through_on_read(self):
        # Legacy rows written before §68 stay readable (re-encrypted on write).
        assert decrypt_credentials_dict({"token": "plain"}, store=EnvelopeSecretStore(_key())) == {
            "token": "plain"
        }

    def test_empty_dict(self):
        assert encrypt_credentials_dict({}, store=EnvelopeSecretStore(_key())) == {}
        assert decrypt_credentials_dict({}, store=EnvelopeSecretStore(_key())) == {}


class TestRotation:
    """§69: a candidate key must prove the migration path BEFORE switch-over."""

    def test_valid_candidate_passes_the_canary(self):
        current = EnvelopeSecretStore(_key(b"c"))
        candidate = validate_rotation_candidate(_key(b"n"), current=current)
        # The candidate carries the old key in its ring: old rows still read.
        legacy = current.encrypt("row-written-before-rotation")
        assert candidate.decrypt(legacy).value == "row-written-before-rotation"

    def test_invalid_candidate_rejected(self):
        current = EnvelopeSecretStore(_key(b"c"))
        with pytest.raises(SecretKeyError):
            validate_rotation_candidate("!!! not base64 !!!", current=current)
        with pytest.raises(SecretKeyError):
            validate_rotation_candidate(base64.b64encode(b"tiny").decode(), current=current)


class TestPersistedCredentials:
    """DB-backed: credentials at rest are ciphertext, reads audit once."""

    async def test_credentials_stored_encrypted_and_reads_audited(self, db, tenant_ctx):
        import sqlalchemy as sa

        from app.core.secrets import get_envelope_store
        from app.modules.platform.models import AuditLog, Integration
        from app.modules.platform.service import IntegrationCredentialsService

        store = get_envelope_store()
        integration = Integration(
            tenant_id=tenant_ctx.tenant.id,
            provider="whatsapp",
            kind="channel",
            credentials=encrypt_credentials_dict(
                {"access_token": "EAA-secret-token", "app_id": 123}, store=store
            ),
        )
        db.add(integration)
        await db.flush()

        # At rest: the raw column holds v1 ciphertext, never the token.
        raw = (
            await db.execute(
                sa.select(Integration.credentials).where(Integration.id == integration.id)
            )
        ).scalar_one()
        assert "EAA-secret-token" not in str(raw)
        assert raw["access_token"].startswith("v1:")

        # Read path: transparent decrypt + exactly ONE audit row per scope,
        # even across two decryptions of the same integration.
        first = await IntegrationCredentialsService.decrypt(db, integration)
        second = await IntegrationCredentialsService.decrypt(db, integration)
        assert first == second == {"access_token": "EAA-secret-token", "app_id": 123}

        rows = (
            (
                await db.execute(
                    sa.select(AuditLog).where(
                        AuditLog.tenant_id == tenant_ctx.tenant.id,
                        AuditLog.action == IntegrationCredentialsService.READ_ACTION,
                        AuditLog.resource_id == str(integration.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_tampered_stored_value_raises_on_read(self, db, tenant_ctx):
        from app.core.secrets import get_envelope_store
        from app.modules.platform.models import Integration
        from app.modules.platform.service import IntegrationCredentialsService

        store = get_envelope_store()
        integration = Integration(
            tenant_id=tenant_ctx.tenant.id,
            provider="whatsapp",
            kind="channel",
            credentials=encrypt_credentials_dict({"access_token": "real"}, store=store),
        )
        db.add(integration)
        await db.flush()
        body = integration.credentials["access_token"][len("v1:") :]
        wrapped_b64, data_b64 = body.split(":")
        raw = bytearray(base64.b64decode(data_b64))
        raw[-1] ^= 0xFF
        integration.credentials = {
            "access_token": "v1:" + wrapped_b64 + ":" + base64.b64encode(bytes(raw)).decode()
        }
        await db.flush()
        with pytest.raises(SecretDecryptionError):
            await IntegrationCredentialsService.decrypt(db, integration)


class TestSerializerLeakage:
    """Spot-check that no read path hands credential material to a response."""

    def test_channel_serializer_exposes_no_credential_material(self):
        # Fail-first: if _integration_output ever starts forwarding the
        # credentials column (even as ciphertext), the two assertions below
        # fail — the serialized dict is exactly what the API returns.
        from types import SimpleNamespace

        from app.modules.customers.router import _integration_output

        integration = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            provider="whatsapp",
            kind="channel",
            status="active",
            config={"_connection": {"verified_at": "2026-01-01T00:00:00Z"}},
            webhook_health=None,
            credentials={"access_token": "v1:SECRETCIPHERTEXT"},
        )
        out = _integration_output(integration)
        assert "credentials" not in out
        assert "SECRETCIPHERTEXT" not in str(out)
