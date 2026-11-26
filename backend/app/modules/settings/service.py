"""Settings service: resolve, read, write, and audit configuration values.

This is the ONLY writer of ``tenant_settings`` and ``tenant_settings_history``.
Every caller (routers, services, workers) goes through here. The service never
commits; the caller owns the transaction (AGENTS.md rule 6).

The resolver walks the inheritance chain at read time. The chain is read from the
database (``scope_graph``), never supplied by the caller:

    register -> pos_profile -> warehouse -> branch -> tenant -> registry default

A value at a lower scope overrides a higher one. When no override exists at any
scope, the registry default is returned. The response always says WHERE the value
came from and whether it is inherited.

Writes
------
* the key must exist in the registry and allow the scope;
* the scope entity must be a row of this tenant (``scope_graph``);
* the caller must be allowed to write that key at that scope (``policy``);
* the value is validated and coerced by the definition;
* one row is appended to ``tenant_settings_history`` and, for keys declared
  ``audit=True``, one row to the central ``audit_logs`` as well.

A write that changes nothing (same value) records nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_row
from app.core.errors import ConflictError, ValidationError
from app.core.events.writer import add_outbox_event
from app.modules.settings.models import (
    SettingChangeRequest,
    TenantSetting,
    TenantSettingHistory,
)
from app.modules.settings.policy import authorize_write
from app.modules.settings.registry import (
    ApplyMode,
    Scope,
    SettingDef,
    REGISTRY,
    get_definition,
    list_definitions,
)
from app.modules.settings.scope_graph import ScopeLink, require_scope_entity, resolve_chain


@dataclass(frozen=True, slots=True)
class ResolvedSetting:
    """The result of resolving one setting key at a scope."""

    key: str
    value: Any
    scope: str  # the scope where the value was found ("default" = registry default)
    scope_id: uuid.UUID | None
    is_inherited: bool  # True if the value comes from a parent scope or the default
    is_default: bool  # True if the value is the registry default
    definition: SettingDef
    # The latest history row id for this key+scope, for optimistic-concurrency
    # checks on write (§81). None when no history exists yet. Populated by
    # ``resolve_many`` so the frontend can pass it back on save.
    latest_history_id: uuid.UUID | None = None


def _s(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _scope(scope: Scope | str) -> Scope:
    try:
        return Scope(scope) if isinstance(scope, str) else scope
    except ValueError:
        raise ValidationError(f"unknown scope {scope!r}") from None


def _definition(key: str) -> SettingDef:
    try:
        return get_definition(key)
    except KeyError:
        raise ValidationError(f"unknown setting {key!r}") from None


def _validate(defn: SettingDef, value: Any) -> Any:
    """Run the definition's validation; a bad value is a 400, never a 500."""
    try:
        return defn.validate(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None


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
    ) -> ResolvedSetting:
        """Resolve one setting to its effective value at the given scope."""
        return (await self.resolve_many([key], scope=scope, scope_id=scope_id))[key]

    async def resolve_many(
        self,
        keys: list[str],
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
    ) -> dict[str, ResolvedSetting]:
        """Resolve several settings with one chain lookup and one override query."""
        scope_enum = _scope(scope)
        defs = {k: _definition(k) for k in keys}
        chain = await resolve_chain(self._session, self._tenant_id, scope_enum, scope_id)
        rows = await self._load_overrides(list(defs), chain)

        out: dict[str, ResolvedSetting] = {}
        for key, defn in defs.items():
            out[key] = self._pick(key, defn, chain, rows)

        # Batch-load the latest history ids for optimistic-concurrency (§81).
        history_ids = await self._latest_history_ids(list(defs), scope_enum.value, scope_id)
        out = {
            k: ResolvedSetting(
                key=r.key,
                value=r.value,
                scope=r.scope,
                scope_id=r.scope_id,
                is_inherited=r.is_inherited,
                is_default=r.is_default,
                latest_history_id=history_ids.get(k),
                definition=r.definition,
            )
            for k, r in out.items()
        }
        return out

    async def resolve_domain(
        self,
        domain: str,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
    ) -> dict[str, ResolvedSetting]:
        """Resolve all settings in a domain (e.g. 'pos')."""
        keys = [d.key for d in list_definitions(domain=domain)]
        return await self.resolve_many(keys, scope=scope, scope_id=scope_id)

    async def value(
        self,
        key: str,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
    ) -> Any:
        """The effective value only. The call operational code makes."""
        return (await self.resolve(key, scope=scope, scope_id=scope_id)).value

    @staticmethod
    def _pick(
        key: str,
        defn: SettingDef,
        chain: list[ScopeLink],
        rows: dict[tuple[str, str, uuid.UUID | None], TenantSetting],
    ) -> ResolvedSetting:
        requested = chain[0]
        for link in chain:
            # A scope the key does not allow can never hold an override for it.
            if not defn.scope_allowed(link.scope):
                continue
            row = rows.get((key, link.scope.value, link.scope_id))
            if row is not None:
                return ResolvedSetting(
                    key=key,
                    value=row.value.get("v"),
                    scope=link.scope.value,
                    scope_id=link.scope_id,
                    is_inherited=link != requested,
                    is_default=False,
                    definition=defn,
                )
        return ResolvedSetting(
            key=key,
            value=defn.default,
            scope="default",
            scope_id=None,
            is_inherited=True,
            is_default=True,
            definition=defn,
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
        permissions: Collection[str] | None = None,
        expected_history_id: uuid.UUID | None = None,
        bypass_approval: bool = False,
        source: str = "api",
    ) -> TenantSetting:
        """Set one setting at the given scope. Creates or updates the override.

        ``permissions`` is the caller's permission codes. ``None`` means an internal
        caller that already holds owner rights (presets applied at signup, workers).

        ``expected_history_id`` implements optimistic concurrency (§81): the caller
        passes the history id it last saw. If another write landed in between,
        the history no longer matches and a ``ConflictError`` is raised instead of
        silently overwriting the newer value.

        ``bypass_approval``: when ``False`` (the default for API callers) and the
        setting's ``apply_mode`` is ``APPROVAL_REQUIRED``, the write is refused —
        the caller must go through ``create_change_request`` instead. Internal
        callers (presets, restore, rollback, approved change requests) pass
        ``True`` because the approval has already been obtained or the operation
        is an administrative recovery.

        ``source`` records where the change originated (api, preset, restore,
        migration, rollback, change_request) in the audit history.
        """
        defn = _definition(key)
        scope_enum = _scope(scope)

        # Sensitive settings (APPROVAL_REQUIRED) may not be written directly from
        # the API — they must go through the change-request approval flow (§172).
        if not bypass_approval and defn.apply_mode == ApplyMode.APPROVAL_REQUIRED:
            raise ValidationError(
                f"{key}: this setting requires approval. "
                "Submit a change request via POST /settings/change-requests instead."
            )

        if not defn.scope_allowed(scope_enum):
            raise ValidationError(
                f"{key}: scope {scope_enum.value!r} not allowed "
                f"(allowed: {[s.value for s in defn.scopes]})"
            )
        await require_scope_entity(self._session, self._tenant_id, scope_enum, scope_id)
        self._authorize(defn, scope_enum, scope_id, user_id, permissions)

        validated = _validate(defn, value)
        new_value = {"v": validated}

        # Lock the existing row (if any) so two concurrent writers serialise and the
        # history's "old value" is the value this write really replaced.
        existing = await self._find_override(key, scope_enum.value, scope_id, for_update=True)

        # Optimistic concurrency: re-check AFTER acquiring the row lock (§81).
        # The check must happen here — not before the lock — so that two concurrent
        # writers serialise: the first acquires the lock, writes, commits; the second
        # waits, then sees the new history id and gets a 409 instead of overwriting.
        if expected_history_id is not None:
            latest = await self._latest_history_id(key, scope_enum.value, scope_id)
            if latest is not None and latest != expected_history_id:
                raise ConflictError(
                    f"{key}: settings changed by another user; reload and try again",
                    details={"conflicting_keys": [key]},
                )
        if existing is not None:
            if existing.value == new_value:
                return existing  # nothing changed, nothing to record
            old_value = existing.value
            existing.value = new_value
            existing.updated_by = user_id
            row = existing
            await self._session.flush()
        else:
            old_value = None
            # ON CONFLICT closes the race where two requests both saw "no row": the
            # loser updates the winner's row instead of failing on the unique key.
            stmt = (
                pg_insert(TenantSetting)
                .values(
                    tenant_id=self._tenant_id,
                    key=key,
                    scope=scope_enum.value,
                    scope_id=scope_id,
                    value=new_value,
                    updated_by=user_id,
                )
                .on_conflict_do_update(
                    constraint="uq_tenant_settings_key_scope",
                    set_={"value": new_value, "updated_by": user_id},
                )
                .returning(TenantSetting.id)
            )
            row_id = (await self._session.execute(stmt)).scalar_one()
            row = await self._session.get(TenantSetting, row_id, populate_existing=True)
            assert row is not None  # just written in this transaction

        await self._record(
            defn,
            row_id=row.id,
            scope=scope_enum,
            scope_id=scope_id,
            old=old_value,
            new=new_value,
            action="set",
            user_id=user_id,
            reason=reason,
            source=source,
        )
        return row

    async def reset(
        self,
        key: str,
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
        permissions: Collection[str] | None = None,
        bypass_approval: bool = False,
        source: str = "api",
    ) -> bool:
        """Remove an override, reverting the scope to its inherited value.

        Returns True if an override was removed, False if none existed.

        ``bypass_approval`` and ``source`` work the same as for ``set``.
        """
        defn = _definition(key)
        scope_enum = _scope(scope)

        if not bypass_approval and defn.apply_mode == ApplyMode.APPROVAL_REQUIRED:
            raise ValidationError(
                f"{key}: this setting requires approval. "
                "Submit a change request via POST /settings/change-requests instead."
            )

        await require_scope_entity(self._session, self._tenant_id, scope_enum, scope_id)
        self._authorize(defn, scope_enum, scope_id, user_id, permissions)

        existing = await self._find_override(key, scope_enum.value, scope_id, for_update=True)
        if existing is None:
            return False

        old_value = existing.value
        # History first, while the setting id is still valid; the FK is SET NULL
        # so the history row survives the delete below.
        await self._record(
            defn,
            row_id=existing.id,
            scope=scope_enum,
            scope_id=scope_id,
            old=old_value,
            new=None,
            action="reset",
            user_id=user_id,
            reason=reason,
            source=source,
        )
        await self._session.execute(delete(TenantSetting).where(TenantSetting.id == existing.id))
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
        permissions: Collection[str] | None = None,
        bypass_approval: bool = False,
        source: str = "api",
        expected_history_ids: dict[str, uuid.UUID] | None = None,
    ) -> list[TenantSetting]:
        """Set several settings. All-or-nothing: every key is checked before any write.

        The caller owns the transaction, so a failure part-way would roll back anyway;
        validating first means the error names the bad key without touching the database.

        ``expected_history_ids`` maps each key to the history id the caller last saw;
        if any key has been changed since, a ``ConflictError`` is raised (§81).
        """
        scope_enum = _scope(scope)
        await require_scope_entity(self._session, self._tenant_id, scope_enum, scope_id)
        checked: dict[str, SettingDef] = {}
        for key, value in settings.items():
            defn = _definition(key)
            if not defn.scope_allowed(scope_enum):
                raise ValidationError(
                    f"{key}: scope {scope_enum.value!r} not allowed "
                    f"(allowed: {[s.value for s in defn.scopes]})"
                )
            self._authorize(defn, scope_enum, scope_id, user_id, permissions)
            _validate(defn, value)
            checked[key] = defn

        # The write loop raises on the FIRST stale key, so a save that lost two keys made the
        # owner fix one, reload and hit a second 409 for the next. One read of the batch names
        # every key that moved, and the per-key check inside `set` stays as the race guard.
        if expected_history_ids:
            expected = {k: expected_history_ids[k] for k in checked if expected_history_ids.get(k)}
            if expected:
                latest = await self._latest_history_ids(list(expected), scope_enum.value, scope_id)
                stale = sorted(k for k, h in expected.items() if latest.get(k) not in (None, h))
                if stale:
                    raise ConflictError(
                        "settings changed by another user: " + ", ".join(stale),
                        details={"conflicting_keys": stale},
                    )

        results = []
        for key, value in settings.items():
            results.append(
                await self.set(
                    key,
                    value,
                    scope=scope_enum,
                    scope_id=scope_id,
                    user_id=user_id,
                    reason=reason,
                    permissions=permissions,
                    bypass_approval=bypass_approval,
                    source=source,
                    expected_history_id=(
                        expected_history_ids.get(key) if expected_history_ids else None
                    ),
                )
            )
        return results

    async def preview(
        self,
        settings: dict[str, Any],
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        permissions: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """What ``bulk_set`` would do, with nothing written.

        Same checks in the same order — definition, scope, authorisation, value — but every
        key is reported instead of the first bad one raising: the point of a dry run is to
        see the whole diff, including which keys need approval, before anything is saved.
        Reads the current effective values and writes nothing.
        """
        scope_enum = _scope(scope)
        await require_scope_entity(self._session, self._tenant_id, scope_enum, scope_id)
        # Resolve only the keys the registry knows: an unknown key is one row of the report
        # ("invalid: unknown setting"), not a 400 that hides the other 20 keys in the batch.
        known = [k for k in settings if k in REGISTRY]
        current = (
            await self.resolve_many(known, scope=scope_enum, scope_id=scope_id) if known else {}
        )
        entries: list[dict[str, Any]] = []
        summary = {"changes": 0, "unchanged": 0, "needs_approval": 0, "invalid": 0}
        for key, value in settings.items():
            resolved = current.get(key)
            entry: dict[str, Any] = {
                "key": key,
                "current": resolved.value if resolved is not None else None,
                "proposed": value,
                "action": "change",
                "needs_approval": False,
                "error": None,
            }
            try:
                defn = _definition(key)
                entry["needs_approval"] = defn.apply_mode == ApplyMode.APPROVAL_REQUIRED
                if not defn.scope_allowed(scope_enum):
                    raise ValidationError(
                        f"{key}: scope {scope_enum.value!r} not allowed "
                        f"(allowed: {[s.value for s in defn.scopes]})"
                    )
                self._authorize(defn, scope_enum, scope_id, user_id, permissions)
                # The coerced value, so the preview shows what would actually be stored.
                entry["proposed"] = _validate(defn, value)
            except ValidationError as exc:
                entry["error"] = str(exc)
                entry["action"] = "invalid"
            if entry["action"] == "change" and entry["current"] == entry["proposed"]:
                entry["action"] = "unchanged"
            if entry["action"] == "change":
                summary["changes"] += 1
            elif entry["action"] == "unchanged":
                summary["unchanged"] += 1
            else:
                summary["invalid"] += 1
            if entry["needs_approval"] and entry["action"] == "change":
                summary["needs_approval"] += 1
            entries.append(entry)
        return {
            "scope": scope_enum.value,
            "scope_id": scope_id,
            "keys": entries,
            "summary": summary,
        }

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
        stmt = select(TenantSetting).where(TenantSetting.tenant_id == self._tenant_id)
        if scope is not None:
            stmt = stmt.where(TenantSetting.scope == _scope(scope).value)
        if scope_id is not None:
            stmt = stmt.where(TenantSetting.scope_id == scope_id)
        if domain is not None:
            stmt = stmt.where(TenantSetting.key.startswith(f"{domain}."))
        result = await self._session.execute(stmt.order_by(TenantSetting.key))
        return list(result.scalars().all())

    async def history(
        self,
        *,
        key: str | None = None,
        source: str | None = None,
        action: str | None = None,
        changed_by: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[TenantSettingHistory]:
        """Return the change history, newest first, with optional filters (§174).

        Filters:
        * ``key`` — only changes to this setting key.
        * ``source`` — only changes from this source (api, preset, restore, …).
        * ``action`` — only this action (set, reset, bulk_set).
        * ``changed_by`` — only changes by this user id.
        * ``since`` / ``until`` — time range (inclusive on both ends).
        """
        stmt = select(TenantSettingHistory).where(TenantSettingHistory.tenant_id == self._tenant_id)
        if key is not None:
            stmt = stmt.where(TenantSettingHistory.key == key)
        if source is not None:
            stmt = stmt.where(TenantSettingHistory.source == source)
        if action is not None:
            stmt = stmt.where(TenantSettingHistory.action == action)
        if changed_by is not None:
            stmt = stmt.where(TenantSettingHistory.changed_by == changed_by)
        if since is not None:
            stmt = stmt.where(TenantSettingHistory.created_at >= since)
        if until is not None:
            stmt = stmt.where(TenantSettingHistory.created_at <= until)
        stmt = stmt.order_by(TenantSettingHistory.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # CHANGE MANAGEMENT: create, approve, apply change requests (§27–§30)
    # ------------------------------------------------------------------

    async def create_change_request(
        self,
        changes: dict[str, Any],
        *,
        scope: Scope | str = Scope.TENANT,
        scope_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
        permissions: Collection[str] | None = None,
    ) -> SettingChangeRequest:
        """Create a change request for settings that need approval (§28).

        For ``IMMEDIATE`` settings, the caller uses ``set`` directly — no
        request is created. For ``VALIDATED`` settings, the request is
        created and immediately validated+applied. For ``APPROVAL_REQUIRED``
        settings, the request stays in ``pending_approval`` until a reviewer
        approves it.
        """
        scope_enum = _scope(scope)
        await require_scope_entity(self._session, self._tenant_id, scope_enum, scope_id)

        # Validate all keys and values upfront.
        needs_approval = False
        for key, value in changes.items():
            defn = _definition(key)
            if not defn.scope_allowed(scope_enum):
                raise ValidationError(f"{key}: scope {scope_enum.value!r} not allowed")
            self._authorize(defn, scope_enum, scope_id, user_id, permissions)
            _validate(defn, value)
            if defn.apply_mode == ApplyMode.APPROVAL_REQUIRED:
                needs_approval = True

        request = SettingChangeRequest(
            tenant_id=self._tenant_id,
            changes=changes,
            status="pending_approval" if needs_approval else "approved",
            scope=scope_enum.value,
            scope_id=scope_id,
            submitted_by=user_id,
            reason=reason,
        )
        self._session.add(request)
        await self._session.flush()

        # If no approval needed, apply immediately.
        if not needs_approval:
            await self._apply_change_request(request, user_id=user_id, permissions=permissions)

        return request

    async def approve_change_request(
        self,
        request_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        review_note: str | None = None,
        permissions: Collection[str] | None = None,
    ) -> SettingChangeRequest:
        """Approve a pending change request and apply it (§28, §172).

        A reviewer may **not** approve their own request — a second admin must
        sign off (§172 self-approval guard).
        """
        stmt = select(SettingChangeRequest).where(
            SettingChangeRequest.tenant_id == self._tenant_id,
            SettingChangeRequest.id == request_id,
        )
        request = (await self._session.execute(stmt)).scalar_one_or_none()
        if request is None:
            raise ValidationError(f"change request {request_id} not found")
        if request.status != "pending_approval":
            raise ValidationError(f"change request is {request.status}, not pending_approval")
        if request.submitted_by is not None and request.submitted_by == reviewer_id:
            raise ValidationError("you cannot approve your own change request (§172)")

        request.status = "approved"
        request.reviewed_by = reviewer_id
        request.review_note = review_note
        request.reviewed_at = func.now()
        await self._session.flush()

        # Audit the approval decision itself (§172).
        await write_audit_row(
            self._session,
            self._tenant_id,
            reviewer_id,
            "settings.change_request_approved",
            "setting_change_requests",
            str(request.id),
            before={"status": "pending_approval"},
            after={"status": "approved", "review_note": review_note},
        )

        await self._apply_change_request(request, user_id=reviewer_id, permissions=permissions)
        return request

    async def reject_change_request(
        self,
        request_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        review_note: str | None = None,
    ) -> SettingChangeRequest:
        """Reject a pending change request (§28, §172).

        A reviewer may not reject their own request either — the same
        self-approval guard applies (§172).
        """
        stmt = select(SettingChangeRequest).where(
            SettingChangeRequest.tenant_id == self._tenant_id,
            SettingChangeRequest.id == request_id,
        )
        request = (await self._session.execute(stmt)).scalar_one_or_none()
        if request is None:
            raise ValidationError(f"change request {request_id} not found")
        if request.status != "pending_approval":
            raise ValidationError(f"change request is {request.status}, not pending_approval")
        if request.submitted_by is not None and request.submitted_by == reviewer_id:
            raise ValidationError("you cannot reject your own change request (§172)")

        request.status = "rejected"
        request.reviewed_by = reviewer_id
        request.review_note = review_note
        request.reviewed_at = func.now()
        await self._session.flush()

        # Audit the rejection decision (§172).
        await write_audit_row(
            self._session,
            self._tenant_id,
            reviewer_id,
            "settings.change_request_rejected",
            "setting_change_requests",
            str(request.id),
            before={"status": "pending_approval"},
            after={"status": "rejected", "review_note": review_note},
        )
        return request

    async def list_change_requests(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SettingChangeRequest]:
        """List change requests, optionally filtered by status."""
        stmt = select(SettingChangeRequest).where(SettingChangeRequest.tenant_id == self._tenant_id)
        if status is not None:
            stmt = stmt.where(SettingChangeRequest.status == status)
        stmt = stmt.order_by(SettingChangeRequest.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def _apply_change_request(
        self,
        request: SettingChangeRequest,
        *,
        user_id: uuid.UUID | None,
        permissions: Collection[str] | None,
    ) -> None:
        """Apply the changes in a change request via ``bulk_set``."""
        request.status = "applying"
        await self._session.flush()
        try:
            rows = await self.bulk_set(
                request.changes,
                scope=Scope(request.scope),
                scope_id=request.scope_id,
                user_id=user_id,
                reason=f"change_request:{request.id}",
                permissions=permissions,
                bypass_approval=True,
                source="change_request",
            )
            request.applied_changes = {
                r.key: r.value.get("v") if isinstance(r.value, dict) else r.value for r in rows
            }
            request.status = "applied"
        except Exception:
            request.status = "failed"
            raise
        await self._session.flush()

    # ------------------------------------------------------------------
    # PRESETS: apply a business-type preset
    # ------------------------------------------------------------------

    async def preview_preset(
        self,
        preset_name: str,
    ) -> dict[str, Any]:
        """Dry-run: show what would change if the preset were applied, without writing.

        Returns a dict with:
        * ``preset``: the resolved (merged with parents) preset name.
        * ``chain``: the inheritance chain (root → child).
        * ``changes``: per key, the current effective value and the preset's target value.
        * ``unchanged``: keys whose effective value already matches the preset.
        * ``total_keys``: count of keys in the resolved preset.
        """
        from app.modules.settings.presets import preset_chain, resolve_preset

        merged = resolve_preset(preset_name)
        chain = preset_chain(preset_name)
        resolved = await self.resolve_many(list(merged))

        changes: list[dict[str, Any]] = []
        unchanged: list[str] = []
        for key, target in merged.items():
            current = resolved[key].value
            if current == target:
                unchanged.append(key)
            else:
                changes.append(
                    {
                        "key": key,
                        "current_value": current,
                        "target_value": target,
                        "current_scope": resolved[key].scope,
                        "is_default": resolved[key].is_default,
                    }
                )
        return {
            "preset": preset_name,
            "chain": chain,
            "total_keys": len(merged),
            "changes": changes,
            "unchanged_count": len(unchanged),
            "unchanged": unchanged,
        }

    async def apply_preset(
        self,
        preset_name: str,
        *,
        user_id: uuid.UUID | None = None,
        permissions: Collection[str] | None = None,
        only_missing: bool = False,
        bypass_approval: bool = False,
    ) -> dict[str, Any]:
        """Apply a named preset at tenant scope.

        ``only_missing`` fills in just the keys the owner has never set and leaves every key that
        already has an owner row exactly as it is. The first-run setup uses it, so choosing a
        preset can never overwrite a choice the owner made; the preset screen keeps the default
        (replace everything) because there the owner is asking for exactly that.

        APPROVAL_REQUIRED settings in the preset go through a change request (the
        same path every other write takes) unless ``bypass_approval=True`` is passed
        with the ``settings:emergency_bypass`` permission. The exception is the
        change-request application itself (``_apply_change_request``), which keeps
        its internal ``bypass_approval=True`` because approval has already been obtained.

        Returns a dict with ``applied`` (the immediately-applied rows) and
        ``pending_approval`` (the keys that need a change request).
        """
        from app.modules.settings.presets import PRESETS, resolve_preset

        if preset_name not in PRESETS:
            raise ValidationError(f"unknown preset {preset_name!r}")
        merged = resolve_preset(preset_name)
        if only_missing:
            resolved = await self.resolve_many(list(merged))
            merged = {k: v for k, v in merged.items() if resolved[k].is_default}

        # Split keys: APPROVAL_REQUIRED settings need a change request (unless bypass).
        immediate: dict[str, Any] = {}
        needs_approval: dict[str, Any] = {}
        for key, value in merged.items():
            defn = _definition(key)
            if defn.apply_mode == ApplyMode.APPROVAL_REQUIRED:
                needs_approval[key] = value
            else:
                immediate[key] = value

        if bypass_approval and needs_approval:
            # Emergency path: requires settings:emergency_bypass and independent audit.
            # Fail-closed: permissions=None means no authenticated caller, so reject.
            if permissions is None or "settings:emergency_bypass" not in permissions:
                from app.modules.errors import PermissionDeniedError

                raise PermissionDeniedError(
                    "emergency bypass requires settings:emergency_bypass permission"
                )
            rows = await self.bulk_set(
                {**immediate, **needs_approval},
                scope=Scope.TENANT,
                user_id=user_id,
                reason=f"preset:{preset_name}",
                permissions=permissions,
                bypass_approval=True,
                source="preset",
            )
            await write_audit_row(
                self._session,
                self._tenant_id,
                user_id,
                "settings.emergency_bypass",
                "tenant_settings",
                str(self._tenant_id),
                before={"operation": "apply_preset", "preset": preset_name},
                after={"bypassed_keys": list(needs_approval.keys())},
            )
            await write_audit_row(
                self._session,
                self._tenant_id,
                user_id,
                "settings.preset_applied",
                "tenant_settings",
                str(self._tenant_id),
                before={"preset": preset_name, "keys": list(merged.keys())},
                after={"preset": preset_name, "applied_count": len(rows)},
            )
            return {"applied": rows, "pending_approval": []}

        # Normal path: apply immediate keys, create a change request for the rest.
        rows = []
        if immediate:
            rows = await self.bulk_set(
                immediate,
                scope=Scope.TENANT,
                user_id=user_id,
                reason=f"preset:{preset_name}",
                permissions=permissions,
                bypass_approval=False,
                source="preset",
            )
        pending: list[str] = []
        if needs_approval:
            await self.create_change_request(
                needs_approval,
                scope=Scope.TENANT,
                user_id=user_id,
                reason=f"preset:{preset_name}",
                permissions=permissions,
            )
            pending = list(needs_approval.keys())
        # One audit row for the preset application as a whole (§170).
        await write_audit_row(
            self._session,
            self._tenant_id,
            user_id,
            "settings.preset_applied",
            "tenant_settings",
            str(self._tenant_id),
            before={"preset": preset_name, "keys": list(merged.keys())},
            after={
                "preset": preset_name,
                "applied_count": len(rows),
                "pending_approval": pending,
            },
        )
        return {"applied": rows, "pending_approval": pending}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _authorize(
        defn: SettingDef,
        scope: Scope,
        scope_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        permissions: Collection[str] | None,
    ) -> None:
        if permissions is None:
            return  # internal caller
        authorize_write(defn, scope, scope_id, permissions=permissions, user_id=user_id)

    async def _record(
        self,
        defn: SettingDef,
        *,
        row_id: uuid.UUID,
        scope: Scope,
        scope_id: uuid.UUID | None,
        old: dict | None,
        new: dict | None,
        action: str,
        user_id: uuid.UUID | None,
        reason: str | None,
        source: str = "api",
    ) -> None:
        """Append to the settings history, audit logs, and outbox event.

        The history row, audit row (if applicable), and outbox event all flush
        within the caller's transaction — so a crash can never leave a changed
        setting with no event, or an event with no setting (§38).
        """
        history_row = TenantSettingHistory(
            tenant_id=self._tenant_id,
            setting_id=row_id,
            key=defn.key,
            scope=scope.value,
            scope_id=scope_id,
            old_value=old,
            new_value=new,
            action=action,
            changed_by=user_id,
            change_reason=reason,
            source=source,
            created_at=func.clock_timestamp(),
        )
        self._session.add(history_row)
        await self._session.flush()

        if defn.audit:
            await write_audit_row(
                self._session,
                self._tenant_id,
                user_id,
                f"settings.{action}",
                "tenant_setting",
                str(row_id),
                before={
                    "key": defn.key,
                    "scope": scope.value,
                    "scope_id": _s(scope_id),
                    "value": old,
                },
                after={
                    "key": defn.key,
                    "scope": scope.value,
                    "scope_id": _s(scope_id),
                    "value": new,
                },
            )

        # Stage the settings.changed event in the outbox (§36–§38).
        # The history row's id is the stable revision identifier consumers
        # use for idempotency.
        await add_outbox_event(
            self._session,
            aggregate_type="settings",
            aggregate_id=row_id,
            event_type="settings.changed",
            tenant_id=self._tenant_id,
            producer="settings",
            payload={
                "key": defn.key,
                "scope": scope.value,
                "scope_id": _s(scope_id),
                "revision": str(history_row.id),
                "action": action,
                "changed_by": _s(user_id),
            },
        )

    async def rollback(
        self,
        history_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
        permissions: Collection[str] | None = None,
        bypass_approval: bool = False,
    ) -> TenantSetting | SettingChangeRequest | None:
        """Restore a setting to the value a previous revision held (§34).

        Rollback does NOT delete history or undo the last change. It reads the
        target revision's value, validates it against the current schema, and
        writes a NEW override — so the audit trail is a forward-only chain and
        every state is recoverable.

        For APPROVAL_REQUIRED settings the rollback goes through a change
        request (the same path every other write takes) unless
        ``bypass_approval=True`` is passed with the ``settings:emergency_bypass``
        permission.

        Returns the new ``TenantSetting`` row (or a ``SettingChangeRequest`` if
        approval is needed), or ``None`` if the target was a reset (the override
        is deleted, reverting to inherited).
        """
        stmt = select(TenantSettingHistory).where(
            TenantSettingHistory.tenant_id == self._tenant_id,
            TenantSettingHistory.id == history_id,
        )
        target = (await self._session.execute(stmt)).scalar_one_or_none()
        if target is None:
            raise ValidationError(f"history revision {history_id} not found")

        defn = get_definition(target.key)
        if not defn.rollback_supported:
            raise ValidationError(f"{target.key}: rollback not supported for this setting")

        # The target was a reset: delete the current override if any.
        if target.action == "reset" and target.new_value is None:
            existing = await self._find_override(
                target.key, target.scope, target.scope_id, for_update=True
            )
            if existing is not None:
                await self._record(
                    defn,
                    row_id=existing.id,
                    scope=Scope(target.scope),
                    scope_id=target.scope_id,
                    old=existing.value,
                    new=None,
                    action="reset",
                    user_id=user_id,
                    reason=f"rollback:{history_id}",
                    source="rollback",
                )
                await self._session.execute(
                    delete(TenantSetting).where(TenantSetting.id == existing.id)
                )
                await self._session.flush()
            return None

        # The target was a set: restore its value.
        restore_value = target.new_value.get("v") if target.new_value else None

        # APPROVAL_REQUIRED settings go through a change request unless bypass.
        if defn.apply_mode == ApplyMode.APPROVAL_REQUIRED and not bypass_approval:
            return await self.create_change_request(
                {target.key: restore_value},
                scope=Scope(target.scope),
                scope_id=target.scope_id,
                user_id=user_id,
                reason=reason or f"rollback:{history_id}",
                permissions=permissions,
            )

        if bypass_approval and defn.apply_mode == ApplyMode.APPROVAL_REQUIRED:
            # Emergency path: requires settings:emergency_bypass and independent audit.
            # Fail-closed: permissions=None means no authenticated caller, so reject.
            if permissions is None or "settings:emergency_bypass" not in permissions:
                from app.modules.errors import PermissionDeniedError

                raise PermissionDeniedError(
                    "emergency bypass requires settings:emergency_bypass permission"
                )
            await write_audit_row(
                self._session,
                self._tenant_id,
                user_id,
                "settings.emergency_bypass",
                "tenant_settings",
                str(self._tenant_id),
                before={"operation": "rollback", "history_id": str(history_id)},
                after={"key": target.key, "value": restore_value},
            )

        return await self.set(
            target.key,
            restore_value,
            scope=Scope(target.scope),
            scope_id=target.scope_id,
            user_id=user_id,
            reason=reason or f"rollback:{history_id}",
            permissions=permissions,
            bypass_approval=bypass_approval,
            source="rollback",
        )

    async def _latest_history_id(
        self, key: str, scope: str, scope_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        """The most recent history row id for this key+scope, or None."""
        stmt = (
            select(TenantSettingHistory.id)
            .where(
                TenantSettingHistory.tenant_id == self._tenant_id,
                TenantSettingHistory.key == key,
                TenantSettingHistory.scope == scope,
            )
            .order_by(TenantSettingHistory.created_at.desc())
            .limit(1)
        )
        if scope_id is None:
            stmt = stmt.where(TenantSettingHistory.scope_id.is_(None))
        else:
            stmt = stmt.where(TenantSettingHistory.scope_id == scope_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _latest_history_ids(
        self, keys: list[str], scope: str, scope_id: uuid.UUID | None
    ) -> dict[str, uuid.UUID]:
        """Batch-load the latest history row id per key for one scope (§81)."""
        if not keys:
            return {}
        cond = [
            TenantSettingHistory.tenant_id == self._tenant_id,
            TenantSettingHistory.key.in_(keys),
            TenantSettingHistory.scope == scope,
        ]
        if scope_id is None:
            cond.append(TenantSettingHistory.scope_id.is_(None))
        else:
            cond.append(TenantSettingHistory.scope_id == scope_id)

        # ROW_NUMBER() picks the newest row per key in one query.
        sub = (
            select(
                TenantSettingHistory.key,
                TenantSettingHistory.id,
                func.row_number()
                .over(
                    partition_by=TenantSettingHistory.key,
                    order_by=TenantSettingHistory.created_at.desc(),
                )
                .label("rn"),
            ).where(*cond)
        ).subquery()
        rows = (await self._session.execute(select(sub.c.key, sub.c.id).where(sub.c.rn == 1))).all()
        return {r[0]: r[1] for r in rows}

    async def _load_overrides(
        self, keys: list[str], chain: list[ScopeLink]
    ) -> dict[tuple[str, str, uuid.UUID | None], TenantSetting]:
        """Load the overrides for ``keys`` at exactly the scopes on ``chain``."""
        if not keys:
            return {}
        wanted = {(link.scope.value, link.scope_id) for link in chain}
        stmt = select(TenantSetting).where(
            TenantSetting.tenant_id == self._tenant_id,
            TenantSetting.key.in_(keys),
            TenantSetting.scope.in_({s for s, _ in wanted}),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        # Keep only rows that sit exactly on the chain: a branch override for a
        # DIFFERENT branch must never leak into this branch's answer.
        return {(r.key, r.scope, r.scope_id): r for r in rows if (r.scope, r.scope_id) in wanted}

    async def restore_to_snapshot(
        self,
        snapshot_before: datetime,
        *,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
        permissions: Collection[str] | None = None,
        bypass_approval: bool = False,
    ) -> dict[str, int]:
        """Restore ALL tenant-level settings to their state before ``snapshot_before``.

        Reads the settings history to reconstruct what each tenant-level override
        looked like at the snapshot point, then writes forward-only changes
        (new history rows with ``action="restore"``) to bring the current state
        back in line. Settings that didn't exist at the snapshot are reset
        (override deleted). Keys no longer in the registry are skipped.

        Returns ``{"restored": N, "reset": M, "skipped": K, "pending_approval": P}``.

        APPROVAL_REQUIRED settings are skipped when ``bypass_approval=False``
        (the default): they must go through the change-request flow. With
        ``bypass_approval=True`` (requires ``settings:emergency_bypass``) every
        setting is restored and an independent audit row records the bypass.
        """
        from sqlalchemy import func as sa_func

        if bypass_approval:
            # Fail-closed: permissions=None means no authenticated caller, so reject.
            if permissions is None or "settings:emergency_bypass" not in permissions:
                from app.modules.errors import PermissionDeniedError

                raise PermissionDeniedError(
                    "emergency bypass requires settings:emergency_bypass permission"
                )

        # 1. Reconstruct the target state from history.
        #    For each (key, scope='tenant', scope_id=None), find the latest
        #    history row before snapshot_before.  Its action tells us the state:
        #      set  → override with new_value
        #      reset → no override
        #      bulk_set → override with new_value
        latest_before = (
            select(
                TenantSettingHistory.key,
                TenantSettingHistory.scope,
                TenantSettingHistory.scope_id,
                TenantSettingHistory.action,
                TenantSettingHistory.new_value,
                TenantSettingHistory.created_at,
            )
            .where(
                TenantSettingHistory.tenant_id == self._tenant_id,
                TenantSettingHistory.created_at < snapshot_before,
            )
            .order_by(TenantSettingHistory.created_at.desc())
        ).subquery()

        ranked = (
            select(
                latest_before.c.key,
                latest_before.c.scope,
                latest_before.c.scope_id,
                latest_before.c.action,
                latest_before.c.new_value,
                sa_func.row_number()
                .over(
                    partition_by=(
                        latest_before.c.key,
                        latest_before.c.scope,
                        latest_before.c.scope_id,
                    ),
                    order_by=latest_before.c.created_at.desc(),
                )
                .label("rn"),
            )
        ).subquery()

        rows = (await self._session.execute(select(ranked).where(ranked.c.rn == 1))).all()

        target: dict[tuple[str, str, uuid.UUID | None], dict | None] = {}
        for r in rows:
            key, scope, scope_id, action, new_value = r[0], r[1], r[2], r[3], r[4]
            if action in ("set", "bulk_set") and new_value is not None:
                target[(key, scope, scope_id)] = new_value
            else:
                target[(key, scope, scope_id)] = None

        # 2. Load ALL overrides (including ones not in the history before the
        #    snapshot, which were added after and need to be removed).
        all_overrides = (
            (
                await self._session.execute(
                    select(TenantSetting).where(TenantSetting.tenant_id == self._tenant_id)
                )
            )
            .scalars()
            .all()
        )

        current_map: dict[tuple[str, str, uuid.UUID | None], TenantSetting] = {
            (r.key, r.scope, r.scope_id): r for r in all_overrides
        }

        restored = 0
        reset = 0
        skipped = 0
        pending_approval = 0

        # 3. For each target, apply the change if different from current.
        for (key, scope, scope_id), target_value in target.items():
            try:
                defn = get_definition(key)
            except KeyError:
                skipped += 1
                continue

            # APPROVAL_REQUIRED settings are skipped unless bypass (§172).
            if defn.apply_mode == ApplyMode.APPROVAL_REQUIRED and not bypass_approval:
                pending_approval += 1
                continue

            scope_enum = _scope(scope)
            current = current_map.get((key, scope, scope_id))

            if target_value is not None:
                # Target is an override with a value.
                restore_val = (
                    target_value.get("v") if isinstance(target_value, dict) else target_value
                )
                if current is not None:
                    current_val = (
                        current.value.get("v") if isinstance(current.value, dict) else current.value
                    )
                    if current_val == restore_val:
                        continue  # Already matches
                # Write the restored value.
                await self.set(
                    key,
                    restore_val,
                    scope=scope_enum,
                    scope_id=scope_id,
                    user_id=user_id,
                    reason=reason or f"restore:{snapshot_before.isoformat()}",
                    permissions=permissions,
                    bypass_approval=bypass_approval,
                    source="restore",
                )
                restored += 1
            else:
                # Target is no override (was reset at snapshot time).
                if current is None:
                    continue  # Already matches
                await self.reset(
                    key,
                    scope=scope_enum,
                    scope_id=scope_id,
                    user_id=user_id,
                    reason=reason or f"restore:{snapshot_before.isoformat()}",
                    permissions=permissions,
                    bypass_approval=bypass_approval,
                    source="restore",
                )
                reset += 1

        # 4. Remove overrides that didn't exist at the snapshot (added after).
        target_keys = set(target.keys())
        for (key, scope, scope_id), _row in current_map.items():
            if (key, scope, scope_id) not in target_keys:
                try:
                    defn = get_definition(key)
                except KeyError:
                    skipped += 1
                    continue
                if defn.apply_mode == ApplyMode.APPROVAL_REQUIRED and not bypass_approval:
                    pending_approval += 1
                    continue
                await self.reset(
                    key,
                    scope=_scope(scope),
                    scope_id=scope_id,
                    user_id=user_id,
                    reason=reason or f"restore:{snapshot_before.isoformat()}",
                    permissions=permissions,
                    bypass_approval=bypass_approval,
                    source="restore",
                )
                reset += 1

        if bypass_approval:
            await write_audit_row(
                self._session,
                self._tenant_id,
                user_id,
                "settings.emergency_bypass",
                "tenant_settings",
                str(self._tenant_id),
                before={
                    "operation": "restore_to_snapshot",
                    "snapshot_before": snapshot_before.isoformat(),
                },
                after={"restored": restored, "reset": reset, "skipped": skipped},
            )

        return {
            "restored": restored,
            "reset": reset,
            "skipped": skipped,
            "pending_approval": pending_approval,
        }

    async def _find_override(
        self, key: str, scope: str, scope_id: uuid.UUID | None, *, for_update: bool = False
    ) -> TenantSetting | None:
        stmt = select(TenantSetting).where(
            TenantSetting.tenant_id == self._tenant_id,
            TenantSetting.key == key,
            TenantSetting.scope == scope,
            TenantSetting.scope_id.is_(None)
            if scope_id is None
            else TenantSetting.scope_id == scope_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()
