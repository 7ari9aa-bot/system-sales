"""Settings service — resolve, read, write, and audit configuration values.

This is the ONLY writer of ``tenant_settings`` and ``tenant_settings_history``.
Every caller — routers, services, workers — goes through here. The service
never commits; the caller owns the transaction (AGENTS.md rule 6).

The resolver walks the inheritance chain at read time:
  register → pos_profile → warehouse → branch → tenant → default

A value at a lower scope overrides a higher one. When no override exists
at any scope, the registry's factory default is returned. The response
always says WHETHER the returned value is inherited or explicitly set.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.models import TenantSetting, TenantSettingHistory
from app.modules.settings.registry import (
    SCOPE_PARENT,
    Scope,
    SettingDef,
    get_definition,
    list_definitions,
)


@dataclass(frozen=True, slots=True)
class ResolvedSetting:
    """The result of resolving one setting key at a scope."""

    key: str
    value: Any
    scope: str  # the scope where the value was found
    scope_id: uuid.UUID | None
    is_inherited: bool  # True if the value comes from a parent scope
    is_default: bool  # True if the value is the registry default
    definition: SettingDef


class SettingsService:
    """Hierarchical settings resolver, reader, and writer."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    # ------------------------------------------------------------------
    # READ: resolve one or many settings
    # ------------------------------------------------------------------

    async def resolve(
        self,
        key: str,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        # Parent scope ids for walking up the chain.
        # Map of scope → scope_id: e.g. {branch: wks_id, warehouse: wh_id}
        scope_chain: dict[str, uuid.UUID] | None = None,
    ) -> ResolvedSetting:
        """Resolve one setting to its effective value at the given scope.

        Walks up: requested scope → parent → … → tenant → default.
        """
        defn = get_definition(key)
        scope_enum = Scope(scope) if isinstance(scope, str) else scope

        # Build the lookup chain: from the requested scope up to tenant.
        chain = self._build_chain(scope_enum, scope_id, scope_chain)

        # Query all overrides for this key in one round trip.
        rows = await self._load_overrides(key, chain)

        # Walk the chain from most-specific to least-specific.
        for s, sid in chain:
            row = rows.get((s.value, sid))
            if row is not None:
                return ResolvedSetting(
                    key=key,
                    value=row.value.get("v"),
                    scope=s.value,
                    scope_id=sid,
                    is_inherited=(s != scope_enum or sid != scope_id),
                    is_default=False,
                    definition=defn,
                )

        # No override at any scope: return the factory default.
        return ResolvedSetting(
            key=key,
            value=defn.default,
            scope="default",
            scope_id=None,
            is_inherited=True,
            is_default=True,
            definition=defn,
        )

    async def resolve_many(
        self,
        keys: list[str],
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        scope_chain: dict[str, uuid.UUID] | None = None,
    ) -> dict[str, ResolvedSetting]:
        """Resolve multiple settings in one call (one DB round trip)."""
        scope_enum = Scope(scope) if isinstance(scope, str) else scope
        chain = self._build_chain(scope_enum, scope_id, scope_chain)

        # Load all overrides for all requested keys.
        all_rows = await self._load_overrides_many(keys, chain)

        results: dict[str, ResolvedSetting] = {}
        for key in keys:
            defn = get_definition(key)
            found = False
            for s, sid in chain:
                row = all_rows.get((key, s.value, sid))
                if row is not None:
                    results[key] = ResolvedSetting(
                        key=key,
                        value=row.value.get("v"),
                        scope=s.value,
                        scope_id=sid,
                        is_inherited=(s != scope_enum or sid != scope_id),
                        is_default=False,
                        definition=defn,
                    )
                    found = True
                    break
            if not found:
                results[key] = ResolvedSetting(
                    key=key,
                    value=defn.default,
                    scope="default",
                    scope_id=None,
                    is_inherited=True,
                    is_default=True,
                    definition=defn,
                )
        return results

    async def resolve_domain(
        self,
        domain: str,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        scope_chain: dict[str, uuid.UUID] | None = None,
    ) -> dict[str, ResolvedSetting]:
        """Resolve all settings in a domain (e.g. 'pos')."""
        defs = list_definitions(domain=domain)
        keys = [d.key for d in defs]
        return await self.resolve_many(
            keys, scope=scope, scope_id=scope_id, scope_chain=scope_chain
        )

    # ------------------------------------------------------------------
    # WRITE: set, reset, bulk_set
    # ------------------------------------------------------------------

    async def set(
        self,
        key: str,
        value: Any,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> TenantSetting:
        """Set one setting at the given scope. Creates or updates the override."""
        defn = get_definition(key)
        scope_enum = Scope(scope) if isinstance(scope, str) else scope

        if not defn.scope_allowed(scope_enum):
            raise ValueError(
                f"{key}: scope {scope_enum.value!r} not allowed "
                f"(allowed: {[s.value for s in defn.scopes]})"
            )

        validated = defn.validate(value)

        # Upsert: find existing or create.
        existing = await self._find_override(key, scope_enum.value, scope_id)
        old_value = existing.value if existing else None

        if existing:
            existing.value = {"v": validated}
            existing.updated_by = user_id
            self._session.add(existing)
            row = existing
        else:
            row = TenantSetting(
                tenant_id=self._tenant_id,
                key=key,
                scope=scope_enum.value,
                scope_id=scope_id,
                value={"v": validated},
                updated_by=user_id,
            )
            self._session.add(row)

        await self._session.flush()

        # Audit trail.
        history = TenantSettingHistory(
            tenant_id=self._tenant_id,
            setting_id=row.id,
            key=key,
            scope=scope_enum.value,
            scope_id=scope_id,
            old_value=old_value,
            new_value={"v": validated},
            action="set",
            changed_by=user_id,
            change_reason=reason,
        )
        self._session.add(history)
        await self._session.flush()

        return row

    async def reset(
        self,
        key: str,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> bool:
        """Remove an override, reverting the scope to its inherited value.

        Returns True if an override was removed, False if none existed.
        """
        scope_enum = Scope(scope) if isinstance(scope, str) else scope
        existing = await self._find_override(key, scope_enum.value, scope_id)
        if existing is None:
            return False

        old_value = existing.value

        # Audit trail BEFORE delete, so the setting_id is still valid.
        history = TenantSettingHistory(
            tenant_id=self._tenant_id,
            setting_id=existing.id,
            key=key,
            scope=scope_enum.value,
            scope_id=scope_id,
            old_value=old_value,
            new_value=None,
            action="reset",
            changed_by=user_id,
            change_reason=reason,
        )
        self._session.add(history)
        await self._session.flush()

        await self._session.delete(existing)
        await self._session.flush()
        return True

    async def bulk_set(
        self,
        settings: dict[str, Any],
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> list[TenantSetting]:
        """Set multiple settings at once. All-or-nothing within the caller's transaction."""
        results = []
        for key, value in settings.items():
            row = await self.set(
                key,
                value,
                scope=scope,
                scope_id=scope_id,
                user_id=user_id,
                reason=reason,
            )
            results.append(row)
        return results

    # ------------------------------------------------------------------
    # LIST: overrides at a scope, history
    # ------------------------------------------------------------------

    async def list_overrides(
        self,
        *,
        scope: Scope | str | None = None,
        scope_id: uuid.UUID | None = None,
        domain: str | None = None,
    ) -> list[TenantSetting]:
        """List all explicit overrides, optionally filtered by scope/domain."""
        stmt = select(TenantSetting).where(
            TenantSetting.tenant_id == self._tenant_id,
        )
        if scope is not None:
            scope_val = Scope(scope).value if isinstance(scope, str) else scope.value
            stmt = stmt.where(TenantSetting.scope == scope_val)
        if scope_id is not None:
            stmt = stmt.where(TenantSetting.scope_id == scope_id)
        if domain is not None:
            prefix = f"{domain}."
            stmt = stmt.where(TenantSetting.key.startswith(prefix))
        stmt = stmt.order_by(TenantSetting.key)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def history(
        self,
        *,
        key: str | None = None,
        limit: int = 50,
    ) -> list[TenantSettingHistory]:
        """Return the change history, newest first."""
        stmt = select(TenantSettingHistory).where(
            TenantSettingHistory.tenant_id == self._tenant_id,
        )
        if key is not None:
            stmt = stmt.where(TenantSettingHistory.key == key)
        stmt = stmt.order_by(TenantSettingHistory.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # PRESETS: apply a business-type preset
    # ------------------------------------------------------------------

    async def apply_preset(
        self,
        preset_name: str,
        *,
        user_id: uuid.UUID | None = None,
    ) -> list[TenantSetting]:
        """Apply a named preset (physical_retail, ecommerce, omnichannel,
        enterprise). Returns the settings that were created/updated.
        """
        from app.modules.settings.presets import PRESETS

        preset = PRESETS.get(preset_name)
        if preset is None:
            raise ValueError(f"Unknown preset: {preset_name!r}")

        return await self.bulk_set(
            preset,
            scope=Scope.TENANT,
            user_id=user_id,
            reason=f"preset:{preset_name}",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_chain(
        self,
        scope: Scope,
        scope_id: uuid.UUID | None,
        scope_chain: dict[str, uuid.UUID] | None,
    ) -> list[tuple[Scope, uuid.UUID | None]]:
        """Build the inheritance chain from scope up to tenant."""
        chain: list[tuple[Scope, uuid.UUID | None]] = []
        sc = scope_chain or {}

        current_scope = scope
        current_id = scope_id
        while current_scope is not None:
            chain.append((current_scope, current_id))
            parent = SCOPE_PARENT.get(current_scope)
            if parent is None:
                break
            current_scope = parent
            current_id = sc.get(parent.value) if parent != Scope.TENANT else None

        return chain

    async def _load_overrides(
        self, key: str, chain: list[tuple[Scope, uuid.UUID | None]]
    ) -> dict[tuple[str, uuid.UUID | None], TenantSetting]:
        """Load all overrides for one key along the chain."""
        if not chain:
            return {}

        stmt = select(TenantSetting).where(
            TenantSetting.tenant_id == self._tenant_id,
            TenantSetting.key == key,
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        return {(r.scope, r.scope_id): r for r in rows}

    async def _load_overrides_many(
        self,
        keys: list[str],
        chain: list[tuple[Scope, uuid.UUID | None]],
    ) -> dict[tuple[str, str, uuid.UUID | None], TenantSetting]:
        """Load all overrides for multiple keys along the chain."""
        if not chain or not keys:
            return {}

        stmt = select(TenantSetting).where(
            TenantSetting.tenant_id == self._tenant_id,
            TenantSetting.key.in_(keys),
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        return {(r.key, r.scope, r.scope_id): r for r in rows}

    async def _find_override(
        self, key: str, scope: str, scope_id: uuid.UUID | None
    ) -> TenantSetting | None:
        """Find an existing override row."""
        stmt = select(TenantSetting).where(
            TenantSetting.tenant_id == self._tenant_id,
            TenantSetting.key == key,
            TenantSetting.scope == scope,
        )
        if scope_id is not None:
            stmt = stmt.where(TenantSetting.scope_id == scope_id)
        else:
            stmt = stmt.where(TenantSetting.scope_id.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
