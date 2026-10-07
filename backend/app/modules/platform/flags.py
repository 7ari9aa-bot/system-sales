"""Feature-flag evaluation (spec §76) — one deterministic decision function.

A flag is a *rollout switch*, never an authorization check: it decides whether
an affordance is shown, not whether an actor is allowed to perform an action.
Access control lives in RBAC (``require_permission``); see the router docstring.

``FeatureFlagService.is_enabled`` applies this precedence, in this order:

1. No row exists for ``(tenant_id, feature)`` -> return ``default``. Absence
   means "not rolled out" — never an exception, never a 500.
2. A row exists but ``enabled`` is false -> ``False``.
3. The row is scoped to a workspace and the caller's ``workspace_id`` does not
   match (including "caller supplied none") -> ``False``.
4. The row is scoped to a role and the caller's ``role_code`` does not match
   -> ``False``.
5. ``rollout_percent``: 0 -> ``False``, 100 -> ``True``, otherwise a
   deterministic bucket of ``sha256(f"{tenant_id}:{feature}:{stable_key}")``
   reduced modulo 100 is compared against the percentage.

Every branch of that ladder fails CLOSED: a row the operator never wrote
(a value the write paths cannot produce — an out-of-band edit, a corrupt
import) reads as OFF, never as "on for everyone". An invalid percentage
narrows a rollout; it can never widen one.

Determinism in step 5 is the whole point: the same caller must never flip
between on and off across requests, so the bucket is a pure hash of stable
identifiers — no random source, no clock, no per-request state.

``stable_key`` should be the *user id* when per-user rollout is wanted: every
request from that user hashes to the same bucket, so a user is either inside
the rollout or outside it, consistently. When ``stable_key`` is omitted the
hash uses an empty key component, i.e. tenant-level bucketing — the whole
tenant shares one decision, which is what a tenant-wide gradual rollout wants.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.platform.models import FeatureFlag

ROLLOUT_MIN = 0
ROLLOUT_MAX = 100


def _rollout_bucket(tenant_id: uuid.UUID, feature: str, stable_key: str | None) -> int:
    """Deterministic bucket in ``[0, 100)`` for a rollout decision.

    Pure function of its inputs — see the module docstring for why the bucket
    must be stable across requests. A missing ``stable_key`` hashes the empty
    string, which yields a single tenant-level bucket.
    """
    key = stable_key if stable_key is not None else ""
    digest = hashlib.sha256(f"{tenant_id}:{feature}:{key}".encode()).hexdigest()
    return int(digest, 16) % 100


class FeatureFlagService:
    """Read/evaluate/write feature flags for a tenant."""

    @staticmethod
    async def is_enabled(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        feature: str,
        *,
        workspace_id: uuid.UUID | None = None,
        role_code: str | None = None,
        stable_key: str | None = None,
        default: bool = False,
    ) -> bool:
        """Decide whether ``feature`` is on for this caller.

        Precedence is documented on the module; it is implemented below in the
        same order so the two cannot drift.
        """
        row = (
            await session.execute(
                select(FeatureFlag).where(
                    FeatureFlag.tenant_id == tenant_id,
                    FeatureFlag.feature == feature,
                )
            )
        ).scalar_one_or_none()

        # 1. Absent -> the caller-supplied default ("not rolled out").
        if row is None:
            return default
        # 2. Explicitly switched off.
        if not row.enabled:
            return False
        # 3. Workspace scope: a scoped row applies only to that workspace.
        if row.workspace_id is not None and row.workspace_id != workspace_id:
            return False
        # 4. Role scope: a scoped row applies only to that role.
        if row.role_code is not None and row.role_code != role_code:
            return False
        # 5. Percentage rollout, bucketed deterministically. A stored value the
        # write paths cannot produce (out-of-band edit, corrupt row) fails
        # CLOSED: it reads as off until the operator repairs the row. Reading
        # an invalid percentage must never *widen* the rollout — before this
        # guard, a corrupt 150 hit the ``>= 100`` branch and read as ON.
        percent = row.rollout_percent
        if not isinstance(percent, int) or not ROLLOUT_MIN <= percent <= ROLLOUT_MAX:
            return False
        if percent <= ROLLOUT_MIN:
            return False
        if percent >= ROLLOUT_MAX:
            return True
        return _rollout_bucket(tenant_id, feature, stable_key) < percent

    @staticmethod
    async def set_flag(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        feature: str,
        *,
        enabled: bool,
        workspace_id: uuid.UUID | None = None,
        role_code: str | None = None,
        rollout_percent: int = 100,
    ) -> FeatureFlag:
        """Create or replace the tenant's flag for ``feature`` (idempotent).

        ``feature_flags`` is unique on ``(tenant_id, feature)``, so this is a
        single ``INSERT ... ON CONFLICT DO UPDATE``: calling it twice with the
        same arguments leaves exactly one row in the same state.
        """
        if not ROLLOUT_MIN <= rollout_percent <= ROLLOUT_MAX:
            raise ValidationError(
                f"rollout_percent must be between {ROLLOUT_MIN} and {ROLLOUT_MAX}",
                details={"rollout_percent": rollout_percent},
            )
        stmt = (
            pg_insert(FeatureFlag)
            .values(
                tenant_id=tenant_id,
                feature=feature,
                enabled=enabled,
                workspace_id=workspace_id,
                role_code=role_code,
                rollout_percent=rollout_percent,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "feature"],
                set_={
                    "enabled": enabled,
                    "workspace_id": workspace_id,
                    "role_code": role_code,
                    "rollout_percent": rollout_percent,
                    # TimestampMixin.onupdate is ORM-only; a Core upsert must
                    # set updated_at itself or the column goes stale.
                    "updated_at": func.now(),
                },
            )
            .returning(FeatureFlag)
        )
        return (await session.execute(stmt)).scalar_one()

    @staticmethod
    async def list_flags(session: AsyncSession, tenant_id: uuid.UUID) -> list[FeatureFlag]:
        """Every flag configured for the tenant, ordered by feature name."""
        rows = (
            (
                await session.execute(
                    select(FeatureFlag)
                    .where(FeatureFlag.tenant_id == tenant_id)
                    .order_by(FeatureFlag.feature)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
