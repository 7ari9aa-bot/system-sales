"""Spec §68-69 — SecretStorePort + rotation.

A Secret is an encrypted value that lives OUTSIDE the database: API tokens,
provider credentials, signing keys. The database stores a REFERENCE to the
secret (a key like "wa_token_<tenant>_<channel_account>"), never the value
itself.

The port has two implementations:
- EnvSecretStore: reads from environment variables (for local/dev). The key
  is the env var name, the value is the env var value. No rotation.
- InMemorySecretStore: for tests. Rotations are tracked for assertions.

§69 rotation: when a secret is rotated, the old version stays available for
a grace period so a consumer reading the secret during a request does not
race the rotation. The port's `get_or_none(key)` always returns the NEWEST
non-expired version.

This module deliberately does NOT implement a cloud KMS / Vault adapter —
that is a deployment concern. The port is the boundary; the deployment plugs
in the concrete adapter.

At-rest column encryption (§68) is a separate concern from the port:
`EnvelopeSecretStore` encrypts values that MUST live in the database
(Integration.credentials) with AES-256-GCM envelope encryption, and
`rotate_master_key` implements the §69 validate-then-switch flow for the
master key.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SecretVersion:
    """One version of a secret's value + metadata."""

    value: str
    version: int
    created_at: float  # epoch
    expires_at: float | None = None  # when this version is no longer served


class SecretStorePort(Protocol):
    """§68: the boundary for reading and rotating secrets.

    A port (not an ABC) because the application layer depends on the shape,
    not a concrete adapter. The infrastructure layer provides an adapter that
    implements this shape (EnvSecretStore for dev, VaultAdapter for prod).
    """

    async def get_or_none(self, key: str) -> str | None:
        """Return the newest non-expired value, or None if the key is unknown."""
        ...

    async def put(self, key: str, value: str, *, ttl_seconds: int | None = None) -> int:
        """Store a new version. Returns the new version number."""
        ...

    async def rotate(self, key: str, new_value: str, grace_seconds: int = 300) -> int:
        """§69: replace the value, keeping the old one for grace_seconds."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the secret entirely (no grace)."""
        ...


class EnvSecretStore:
    """§68 dev adapter: reads secrets from environment variables.

    No rotation (the env var is the single version). `rotate` overwrites the
    env var, which is acceptable in dev/tests but NOT in production.
    """

    async def get_or_none(self, key: str) -> str | None:
        return os.environ.get(key)

    async def put(self, key: str, value: str, *, ttl_seconds: int | None = None) -> int:
        os.environ[key] = value
        return 1

    async def rotate(self, key: str, new_value: str, grace_seconds: int = 300) -> int:
        os.environ[key] = new_value
        return 1

    async def delete(self, key: str) -> None:
        os.environ.pop(key, None)


class InMemorySecretStore:
    """§68 test adapter: keeps versions in a dict, supports rotation+grace."""

    _store: dict[str, list[SecretVersion]]
    _version_counter: dict[str, int]

    def __init__(self) -> None:
        self._store = {}
        self._version_counter = {}

    async def get_or_none(self, key: str) -> str | None:
        versions = self._store.get(key)
        if not versions:
            return None
        now = time.time()
        # Return the newest non-expired version
        for v in reversed(versions):
            if v.expires_at is None or v.expires_at > now:
                return v.value
        return None

    async def put(self, key: str, value: str, *, ttl_seconds: int | None = None) -> int:
        ver = self._version_counter.get(key, 0) + 1
        self._version_counter[key] = ver
        now = time.time()
        expires = now + ttl_seconds if ttl_seconds else None
        self._store.setdefault(key, []).append(
            SecretVersion(value=value, version=ver, created_at=now, expires_at=expires)
        )
        return ver

    async def rotate(self, key: str, new_value: str, grace_seconds: int = 300) -> int:
        """§69: add a new version and set the old one to expire after grace."""
        now = time.time()
        old_versions = self._store.get(key, [])
        # Expire all existing versions after the grace period
        for v in old_versions:
            if v.expires_at is None or v.expires_at > now:
                v_with_expiry = SecretVersion(
                    value=v.value,
                    version=v.version,
                    created_at=v.created_at,
                    expires_at=now + grace_seconds,
                )
                # Replace in-place (the list is mutable)
                idx = old_versions.index(v)
                old_versions[idx] = v_with_expiry

        new_ver = self._version_counter.get(key, 0) + 1
        self._version_counter[key] = new_ver
        old_versions.append(
            SecretVersion(value=new_value, version=new_ver, created_at=now, expires_at=None)
        )
        self._store[key] = old_versions
        return new_ver

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._version_counter.pop(key, None)


class DatabaseSecretStore:
    """§68 production adapter: envelope-encrypted versions in Postgres.

    Replaces EnvSecretStore in secure environments — process memory is not a
    secret store: it is invisible to the other uvicorn workers, lost on every
    restart, and has no rotation history. Here every value is encrypted by
    EnvelopeSecretStore (AES-256-GCM) before it touches the database, so the
    ciphertext column alone is useless without SECRETS_MASTER_KEY, and each
    key is versioned so §69 rotation keeps the old version readable for a
    grace period.

    The store is tenant-scoped: it resolves the tenant from the request/worker
    context (app.core.tenancy) and opens its own short-lived session per call
    (the port signature carries neither tenant nor session). Without a tenant
    in context it fails CLOSED (LookupError) rather than guessing a scope.
    """

    def __init__(self, envelope: EnvelopeSecretStore | None = None) -> None:
        self._envelope = envelope

    def _crypto(self) -> EnvelopeSecretStore:
        return self._envelope or get_envelope_store()

    @staticmethod
    def _tenant_id() -> uuid.UUID:
        from app.core.tenancy import try_current_tenant

        tenant_id = try_current_tenant()
        if tenant_id is None:
            raise LookupError(
                "no tenant in context — DatabaseSecretStore is tenant-scoped; "
                "bind the tenant (tenant_scope / request context) first"
            )
        return tenant_id

    async def get_or_none(self, key: str) -> str | None:
        from datetime import UTC, datetime

        from sqlalchemy import or_, select

        from app.core.db import bind_tenant, get_sessionmaker
        from app.modules.platform.models import SecretValue

        tenant_id = self._tenant_id()
        now = datetime.now(UTC)
        async with get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            ciphertext = (
                await session.execute(
                    select(SecretValue.ciphertext)
                    .where(
                        SecretValue.tenant_id == tenant_id,
                        SecretValue.vault_key == key,
                        or_(
                            SecretValue.expires_at.is_(None),
                            SecretValue.expires_at > now,
                        ),
                    )
                    .order_by(SecretValue.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if ciphertext is None:
            return None
        return self._crypto().decrypt(ciphertext).value

    async def put(self, key: str, value: str, *, ttl_seconds: int | None = None) -> int:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import func, select

        from app.core.db import bind_tenant, get_sessionmaker
        from app.modules.platform.models import SecretValue

        tenant_id = self._tenant_id()
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        async with get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            # max over ALL versions, expired included: numbers are never reused.
            current = (
                await session.execute(
                    select(func.coalesce(func.max(SecretValue.version), 0)).where(
                        SecretValue.tenant_id == tenant_id,
                        SecretValue.vault_key == key,
                    )
                )
            ).scalar_one()
            version = current + 1
            session.add(
                SecretValue(
                    tenant_id=tenant_id,
                    vault_key=key,
                    version=version,
                    ciphertext=self._crypto().encrypt(value),
                    expires_at=expires_at,
                )
            )
            await session.commit()
        return version

    async def rotate(self, key: str, new_value: str, grace_seconds: int = 300) -> int:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import func, or_, select

        from app.core.db import bind_tenant, get_sessionmaker
        from app.modules.platform.models import SecretValue

        tenant_id = self._tenant_id()
        now = datetime.now(UTC)
        grace_until = now + timedelta(seconds=grace_seconds)
        async with get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            # §69: the live versions stay readable for the grace window.
            live = (
                (
                    await session.execute(
                        select(SecretValue).where(
                            SecretValue.tenant_id == tenant_id,
                            SecretValue.vault_key == key,
                            or_(
                                SecretValue.expires_at.is_(None),
                                SecretValue.expires_at > now,
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in live:
                row.expires_at = grace_until
            current = (
                await session.execute(
                    select(func.coalesce(func.max(SecretValue.version), 0)).where(
                        SecretValue.tenant_id == tenant_id,
                        SecretValue.vault_key == key,
                    )
                )
            ).scalar_one()
            version = current + 1
            session.add(
                SecretValue(
                    tenant_id=tenant_id,
                    vault_key=key,
                    version=version,
                    ciphertext=self._crypto().encrypt(new_value),
                    expires_at=None,
                )
            )
            await session.commit()
        return version

    async def delete(self, key: str) -> None:
        from sqlalchemy import delete as sa_delete

        from app.core.db import bind_tenant, get_sessionmaker
        from app.modules.platform.models import SecretValue

        tenant_id = self._tenant_id()
        async with get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            await session.execute(
                sa_delete(SecretValue).where(
                    SecretValue.tenant_id == tenant_id,
                    SecretValue.vault_key == key,
                )
            )
            await session.commit()


# Singleton for the app process, resolved lazily from settings: secure
# environments get DatabaseSecretStore (durable, worker-shared, encrypted at
# rest); local/test keeps EnvSecretStore. A secure environment can therefore
# never silently fall back to process memory — the selection is code, not
# configuration. Tests override via set_secret_store().
_store: SecretStorePort | None = None


def _resolve_default_store() -> SecretStorePort:
    from app.core.config import get_settings

    if get_settings().is_secure_environment:
        logger.info("secrets.store=database — envelope-encrypted, tenant-scoped (§68)")
        return DatabaseSecretStore()
    return EnvSecretStore()


def get_secret_store() -> SecretStorePort:
    """Get the process-wide secret store (§68)."""
    global _store
    if _store is None:
        _store = _resolve_default_store()
    return _store


def set_secret_store(store: SecretStorePort) -> None:
    """Override the secret store (for tests or deployment setup)."""
    global _store
    _store = store


def reset_secret_store() -> None:
    """Drop the cached store so the next get re-resolves from settings (tests)."""
    global _store
    _store = None


# ---------------------------------------------------------------------------
# §68 at-rest envelope encryption (values that MUST live in the database)
# ---------------------------------------------------------------------------


class SecretDecryptionError(Exception):
    """A v1 ciphertext could not be decrypted (tampered, or wrong key ring)."""


class SecretKeyError(ValueError):
    """A master key is malformed/weak, or failed rotation validation."""


@dataclass(frozen=True, slots=True)
class DecryptResult:
    """Outcome of a decrypt: the value plus whether it was LEGACY plaintext."""

    value: str
    was_plaintext: bool = False


def _derive_kek(master_key_b64: str) -> bytes:
    """Master key (base64, 32+ bytes decoded) -> 32-byte key-encryption key."""
    try:
        raw = base64.b64decode(master_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretKeyError("master key must be base64-encoded") from exc
    if len(raw) < 32:
        raise SecretKeyError("master key must decode to at least 32 bytes")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"salesos:envelope-kek:v1",
    ).derive(raw)


class EnvelopeSecretStore:
    """§68 v1 envelope encryption for database-resident secrets.

    AES-256-GCM (via `cryptography`) with a fresh random data-encryption key
    (DEK) per value; the DEK is itself wrapped by a KEK derived from the
    configured master key (HKDF-SHA256). Wire format::

        v1:<base64(wrap-nonce + KEK-wrapped DEK)>:<base64(nonce + ciphertext)>

    ``decrypt()`` is backwards-compatible: a value NOT carrying the ``v1:``
    prefix is a legacy plaintext row and is returned as-is with
    ``was_plaintext=True`` so callers can schedule re-encryption. A ``v1:``
    value that fails authentication raises SecretDecryptionError — tampered
    ciphertext is never silently returned.

    Key ring: ``previous_master_keys`` are old master keys kept ONLY for
    decryption during a rotation grace period (§69: never break every request
    at once). Encryption always uses the newest key.
    """

    PREFIX = "v1:"
    _WRAP_AAD = b"salesos:v1:wrap"
    _DATA_AAD = b"salesos:v1:data"
    _NONCE_BYTES = 12  # 96-bit GCM nonce

    def __init__(
        self,
        master_key_b64: str,
        *,
        previous_master_keys: list[str] | None = None,
    ) -> None:
        # The raw master key material is retained so a rotation can carry the
        # whole ring forward (validate_rotation_candidate) — KEKs are derived,
        # and a KEK cannot re-derive itself.
        self._master_key_b64 = master_key_b64
        self._previous_master_keys = list(previous_master_keys or [])
        self._keks: list[bytes] = [_derive_kek(master_key_b64)]
        for old in self._previous_master_keys:
            self._keks.append(_derive_kek(old))

    @classmethod
    def from_settings(cls, settings) -> EnvelopeSecretStore:
        """Build from app config; local/test fall back to a public dev key."""
        master = settings.secrets_master_key
        if not master:
            # Unreachable in secure environments — config.Settings refuses to
            # boot with an empty key there. In local/test we use a PUBLISHED
            # dev-only key so encrypted values are obviously not protected.
            logger.warning(
                "secrets.dev_master_key_in_use — set SECRETS_MASTER_KEY; "
                "values encrypted with the dev key are NOT protected"
            )
            master = _DEV_MASTER_KEY_B64
        previous = [
            k.strip() for k in settings.secrets_previous_master_keys.split(",") if k.strip()
        ]
        return cls(master, previous_master_keys=previous)

    def encrypt(self, plaintext: str) -> str:
        dek = AESGCM.generate_key(bit_length=256)
        wrap_nonce = os.urandom(self._NONCE_BYTES)
        wrapped = wrap_nonce + AESGCM(self._keks[0]).encrypt(wrap_nonce, dek, self._WRAP_AAD)
        nonce = os.urandom(self._NONCE_BYTES)
        ciphertext = nonce + AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), self._DATA_AAD)
        return (
            self.PREFIX
            + base64.b64encode(wrapped).decode("ascii")
            + ":"
            + base64.b64encode(ciphertext).decode("ascii")
        )

    def decrypt(self, value: str) -> DecryptResult:
        if not isinstance(value, str) or not value.startswith(self.PREFIX):
            # Legacy row written before §68 at-rest encryption — readable, and
            # flagged so the caller can re-encrypt on the next write.
            return DecryptResult(value=value, was_plaintext=True)
        body = value[len(self.PREFIX) :]
        try:
            wrapped_b64, ciphertext_b64 = body.split(":")
            wrapped = base64.b64decode(wrapped_b64, validate=True)
            ciphertext = base64.b64decode(ciphertext_b64, validate=True)
            wrap_nonce, wrapped_dek = wrapped[: self._NONCE_BYTES], wrapped[self._NONCE_BYTES :]
            nonce, data = ciphertext[: self._NONCE_BYTES], ciphertext[self._NONCE_BYTES :]
        except (binascii.Error, ValueError) as exc:
            raise SecretDecryptionError("malformed v1 ciphertext") from exc
        for kek in self._keks:
            try:
                dek = AESGCM(kek).decrypt(wrap_nonce, wrapped_dek, self._WRAP_AAD)
                plaintext = AESGCM(dek).decrypt(nonce, data, self._DATA_AAD)
            except InvalidTag:
                continue  # not this key — try the next one in the ring
            return DecryptResult(value=plaintext.decode("utf-8"), was_plaintext=False)
        raise SecretDecryptionError(
            "cannot decrypt value: tampered ciphertext or unknown master key"
        )


# PUBLISHED dev-only fallback — NOT a secret. Used only when SECRETS_MASTER_KEY
# is unset in local/test (secure environments refuse to boot without the key).
_DEV_MASTER_KEY_B64 = base64.b64encode(b"salesos-dev-key-DO-NOT-USE-PROD!").decode("ascii")

_envelope_store: EnvelopeSecretStore | None = None


def get_envelope_store() -> EnvelopeSecretStore:
    """Process-wide at-rest store, built lazily from settings (§68)."""
    global _envelope_store
    if _envelope_store is None:
        from app.core.config import get_settings

        _envelope_store = EnvelopeSecretStore.from_settings(get_settings())
    return _envelope_store


def set_envelope_store(store: EnvelopeSecretStore) -> None:
    """Swap the at-rest store (rotation, tests, deployment setup)."""
    global _envelope_store
    _envelope_store = store


def reset_envelope_store() -> None:
    """Drop the cached store so the next get rebuilds from settings (tests)."""
    global _envelope_store
    _envelope_store = None


# ---------------------------------------------------------------------------
# Integration credentials: per-value encrypt/decrypt over the JSONB dict
# ---------------------------------------------------------------------------


def encrypt_credentials_dict(
    credentials: dict, *, store: EnvelopeSecretStore | None = None
) -> dict:
    """§68 write path: encrypt every value of an Integration.credentials dict.

    Values are JSON-encoded before encryption so non-string scalars round-trip
    with their type. A value already carrying the v1 prefix is kept as-is so
    re-upserts are idempotent (never double-encrypted).
    """
    if not credentials:
        return {}
    s = store or get_envelope_store()
    out: dict = {}
    for key, value in credentials.items():
        if isinstance(value, str) and value.startswith(EnvelopeSecretStore.PREFIX):
            out[key] = value
        else:
            out[key] = s.encrypt(json.dumps(value))
    return out


def decrypt_credentials_dict(
    credentials: dict, *, store: EnvelopeSecretStore | None = None
) -> dict:
    """§68 read path: transparently decrypt a credentials dict.

    Legacy plaintext values (no v1 prefix) pass through untouched — the row
    is re-encrypted the next time it is written. Tampered v1 values raise
    SecretDecryptionError.
    """
    if not credentials:
        return {}
    s = store or get_envelope_store()
    out: dict = {}
    for key, value in credentials.items():
        if isinstance(value, str) and value.startswith(EnvelopeSecretStore.PREFIX):
            result = s.decrypt(value)
            try:
                out[key] = json.loads(result.value)
            except json.JSONDecodeError:
                out[key] = result.value
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# §69 master-key rotation (validate -> switch -> audit)
# ---------------------------------------------------------------------------

# Stable aggregate id for the master key: there is no database row behind it,
# so a namespaced UUID gives the outbox event a constant aggregate identity.
_MASTER_KEY_AGGREGATE_ID = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://salesos.local/secrets/master-key"
)


def validate_rotation_candidate(
    new_master_key_b64: str, *, current: EnvelopeSecretStore | None = None
) -> EnvelopeSecretStore:
    """§69 "validate": prove the candidate key can serve traffic BEFORE switch.

    The candidate is built with the current key in its decryption ring, then
    must round-trip a canary through the full migration path — ciphertext
    produced under the CURRENT key decrypts under the candidate, and a value
    re-encrypted under the candidate decrypts back to the canary. Any failure
    raises and the old key keeps serving.
    """
    old = current or get_envelope_store()
    candidate = EnvelopeSecretStore(
        new_master_key_b64,
        previous_master_keys=[old._master_key_b64, *old._previous_master_keys],
    )
    canary = f"rotation-canary:{uuid.uuid4()}"
    legacy_ciphertext = old.encrypt(canary)  # what existing rows look like
    carried = candidate.encrypt(candidate.decrypt(legacy_ciphertext).value)
    result = candidate.decrypt(carried)
    if result.was_plaintext or result.value != canary:
        raise SecretKeyError("rotation canary round-trip failed — refusing the new master key")
    return candidate


async def rotate_master_key(
    session, new_master_key_b64: str, *, tenant_id: uuid.UUID
) -> EnvelopeSecretStore:
    """§69: validate the new key, switch the process store, emit the audit event.

    Emits ``platform.secret_rotated`` through the outbox inside the CALLER's
    transaction so the rotation is durable and observable. Rows encrypted
    under the old key stay decryptable via the candidate's key ring; a
    follow-up sweep can lazily re-encrypt them (decrypt() flags plaintext).
    """
    from app.core.events.writer import add_outbox_event

    candidate = validate_rotation_candidate(new_master_key_b64)
    set_envelope_store(candidate)
    await add_outbox_event(
        session,
        aggregate_type="platform",
        aggregate_id=_MASTER_KEY_AGGREGATE_ID,
        event_type="platform.secret_rotated",
        tenant_id=tenant_id,
        payload={"rotated_by": "rotate_master_key"},
        # The master key is process config, not an aggregate row: there is no
        # optimistic-concurrency source to increment, so the version is the
        # literal 1 on purpose rather than a fabricated counter.
        aggregate_version=1,
    )
    return candidate
