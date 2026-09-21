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
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol


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
            SecretVersion(
                value=new_value, version=new_ver, created_at=now, expires_at=None
            )
        )
        self._store[key] = old_versions
        return new_ver

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._version_counter.pop(key, None)


# Singleton for the app process. In production, this is replaced by the
# deployment's adapter (Vault, AWS Secrets Manager, etc.).
_store: SecretStorePort = EnvSecretStore()


def get_secret_store() -> SecretStorePort:
    """Get the process-wide secret store (§68)."""
    return _store


def set_secret_store(store: SecretStorePort) -> None:
    """Override the secret store (for tests or deployment setup)."""
    global _store
    _store = store
