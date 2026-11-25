"""Settings event types for the transactional outbox (§36–§38).

When a setting changes, a ``settings.changed`` event is staged in the outbox
in the same transaction as the write. Interested runtime systems (POS,
inventory, agents) consume the event and invalidate their cached config or
reload the effective value — so no part of the system keeps using a stale
setting after the owner changed it.

The event carries:
* ``key``: which setting changed.
* ``scope`` / ``scope_id``: at which scope the override was written or reset.
* ``revision``: the history row id (stable identifier for this change).
* ``changed_by``: who made the change.
* ``action``: ``set`` or ``reset``.
"""

from __future__ import annotations

from typing import Any

from app.core.events.schemas import EventEnvelope, register_event


@register_event("settings.changed")
class SettingsChangedEvent(EventEnvelope):
    """Emitted when a tenant setting is created, updated, or reset.

    Consumers should:
    1. Invalidate any cached value for ``(tenant_id, key, scope, scope_id)``.
    2. Reload the effective value at the scopes that inherit from the changed
       scope (e.g. all branches under a tenant-level change).
    3. Apply idempotency: if the ``revision`` has already been processed, skip.
    """

    def expected_payload_keys(self) -> set[str]:
        return {"key", "scope", "scope_id", "revision", "action", "changed_by"}

    @classmethod
    def build(
        cls,
        *,
        tenant_id: Any,
        key: str,
        scope: str,
        scope_id: str | None,
        revision: str,
        action: str,
        changed_by: str | None,
    ) -> dict[str, Any]:
        """Return the payload dict for ``add_outbox_event``."""
        return {
            "key": key,
            "scope": scope,
            "scope_id": scope_id,
            "revision": revision,
            "action": action,
            "changed_by": changed_by,
        }


@register_event("security.setting_changed")
class SecuritySettingChangedEvent(EventEnvelope):
    """Emitted by the settings consumer when a ``security.*`` setting changes.

    This is a downstream audit event — it is NOT emitted in the same
    transaction as the setting write. The ``SettingsConsumer`` worker reads
    ``settings.changed`` from the outbox stream and, when the key starts with
    ``security.``, stages this event so the platform's security-audit
    pipeline can record who changed a security setting, when, and from where.

    The payload mirrors :class:`SettingsChangedEvent` so the audit pipeline
    gets the same fields the consumer saw.
    """

    def expected_payload_keys(self) -> set[str]:
        return {"key", "scope", "scope_id", "revision", "action", "changed_by"}

    @classmethod
    def build(
        cls,
        *,
        key: str,
        scope: str,
        scope_id: str | None,
        revision: str,
        action: str,
        changed_by: str | None,
    ) -> dict[str, Any]:
        """Return the payload dict for ``add_outbox_event``."""
        return {
            "key": key,
            "scope": scope,
            "scope_id": scope_id,
            "revision": revision,
            "action": action,
            "changed_by": changed_by,
        }
