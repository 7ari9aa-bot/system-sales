"""Secret management and integration credentials services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.context import credentials_audit_contextvar
from app.core.errors import NotFoundError
from app.modules.platform.models import SecretReference, SecurityEvent
from .audit import AuditService


class IntegrationCredentialsService:
    """§68: lazy decryption of Integration.credentials + access auditing.

    Credentials are encrypted at rest (EnvelopeSecretStore, app.core.secrets);
    they are decrypted ONLY at the point a provider call needs them. Every
    decryption is audited (§66 action "integration.credentials.read"), batched
    to ONE row per integration per request/event scope so a chatty consumer
    cannot spam the audit log.
    """

    READ_ACTION = "integration.credentials.read"

    @staticmethod
    async def decrypt(session: Any, integration: Any) -> dict:
        from app.core.secrets import decrypt_credentials_dict

        plaintext = decrypt_credentials_dict(integration.credentials or {})
        await IntegrationCredentialsService._audit_read_once(session, integration)
        return plaintext

    @staticmethod
    async def _audit_read_once(session: Any, integration: Any) -> None:
        seen = credentials_audit_contextvar.get()
        if seen is None:
            # No request/event scope installed a set (script path): scope the
            # batch to this context so the row-per-decrypt spam guard holds.
            seen = set()
            credentials_audit_contextvar.set(seen)
        marker = str(integration.id)
        if marker in seen:
            return
        seen.add(marker)
        await AuditService.write(
            session,
            integration.tenant_id,
            None,  # the ACTOR is carried by the §66 source column
            IntegrationCredentialsService.READ_ACTION,
            "integration",
            str(integration.id),
        )


class SecretService:
    """§68-69: manage secret references + delegate to SecretStorePort.

    Business tables hold SecretReference rows (metadata + vault_key), never
    raw secret values. The actual values live behind SecretStorePort.
    """

    @staticmethod
    async def create_reference(
        session: Any,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        scope: str = "tenant",
        vault_key: str,
        workspace_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        ip: str | None = None,
    ) -> SecretReference:
        """Register a secret reference. The actual value is stored via the port."""
        ref = SecretReference(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            provider=provider,
            scope=scope,
            vault_key=vault_key,
            status="active",
            version=1,
        )
        session.add(ref)
        await session.flush()
        # §67: registering a credential is a security event ("API key
        # created"); the value never touches this table but who wired which
        # provider must be on the trail.
        session.add(
            SecurityEvent(
                event_type="api_key_created",
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                details={"provider": provider, "scope": scope, "vault_key": vault_key},
                ip=ip,
            )
        )
        await session.flush()
        return ref

    @staticmethod
    async def get_secret_value(
        session: Any,
        tenant_id: uuid.UUID,
        provider: str,
    ) -> str | None:
        """Fetch the actual secret value through SecretStorePort (§68)."""
        from app.core.secrets import get_secret_store

        ref = (
            await session.execute(
                select(SecretReference).where(
                    SecretReference.tenant_id == tenant_id,
                    SecretReference.provider == provider,
                    SecretReference.status == "active",
                )
            )
        ).scalar_one_or_none()
        if ref is None:
            return None
        store = get_secret_store()
        return await store.get_or_none(ref.vault_key)

    @staticmethod
    async def rotate_secret(
        session: Any,
        tenant_id: uuid.UUID,
        provider: str,
        new_value: str,
        *,
        actor_user_id: uuid.UUID | None = None,
        ip: str | None = None,
    ) -> SecretReference:
        """§69: rotate a secret — old version stays for grace period.

        §67/§69: rotation is a security event AND an audited mutation, not
        just a column bump — the trail must name who rotated what.
        """
        from app.core.secrets import get_secret_store

        ref = (
            await session.execute(
                select(SecretReference).where(
                    SecretReference.tenant_id == tenant_id,
                    SecretReference.provider == provider,
                    SecretReference.status == "active",
                )
            )
        ).scalar_one_or_none()
        if ref is None:
            raise NotFoundError(f"no secret reference found for provider {provider}")

        store = get_secret_store()
        from_version = ref.version
        new_version = await store.rotate(ref.vault_key, new_value)
        ref.version = new_version
        ref.rotated_at = datetime.now(UTC)
        ref.status = "active"
        await session.flush()

        session.add(
            SecurityEvent(
                event_type="secret_rotated",
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                details={
                    "provider": provider,
                    "vault_key": ref.vault_key,
                    "from_version": from_version,
                    "to_version": new_version,
                },
                ip=ip,
            )
        )
        await AuditService.write(
            session,
            tenant_id,
            actor_user_id,
            "secret.rotated",
            "secret_reference",
            str(ref.id),
            before={"version": from_version},
            after={"version": new_version},
        )
        return ref
