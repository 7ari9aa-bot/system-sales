"""Identity services package.

Re-exports all identity sub-services and helpers for easy access.
"""

from app.platform.identity.services._common import (
    _REFRESH_REUSE_GRACE_SECONDS,
    EmailAlreadyRegistered,
    _dummy_password_hash,
    _hash_token,
    _lockout_op,
    _now,
    _record_audit,
    _record_security_event,
    _revoke_family_on_reuse,
)
from app.platform.identity.services.account_closure import AccountClosureService
from app.platform.identity.services.auth import AuthService, GoogleMfaRequired
from app.platform.identity.services.hierarchy import HierarchyService
from app.platform.identity.services.lifecycle import (
    ALLOWED_TRANSITIONS,
    GRACE_PERIOD_DAYS,
    OFFBOARDING_RETENTION_DAYS,
    PLATFORM_ONLY_LIFECYCLE_TARGETS,
    STATE_POLICIES,
    TENANT_INITIAL_STATE,
    TENANT_LIFECYCLE_STATES,
    TENANT_OPERATIONAL_STATES,
    TENANT_REQUESTABLE_LIFECYCLE_TARGETS,
    TenantCapabilityPolicy,
    TenantLifecycleService,
)
from app.platform.identity.services.session import (
    SignedInDeviceService,
    describe_device,
)
from app.platform.identity.services.settings import (
    TenantSettingsService,
    timezone_refusal,
)
from app.platform.identity.services.tenant import TenantService
from app.platform.identity.services.user import UserService

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AccountClosureService",
    "AuthService",
    "GoogleMfaRequired",
    "EmailAlreadyRegistered",
    "GRACE_PERIOD_DAYS",
    "HierarchyService",
    "OFFBOARDING_RETENTION_DAYS",
    "PLATFORM_ONLY_LIFECYCLE_TARGETS",
    "STATE_POLICIES",
    "TENANT_INITIAL_STATE",
    "TENANT_LIFECYCLE_STATES",
    "TENANT_OPERATIONAL_STATES",
    "TENANT_REQUESTABLE_LIFECYCLE_TARGETS",
    "TenantCapabilityPolicy",
    "TenantLifecycleService",
    "SignedInDeviceService",
    "TenantService",
    "TenantSettingsService",
    "UserService",
    "_REFRESH_REUSE_GRACE_SECONDS",
    "_dummy_password_hash",
    "_hash_token",
    "_lockout_op",
    "_now",
    "_record_audit",
    "_record_security_event",
    "_revoke_family_on_reuse",
    "describe_device",
    "timezone_refusal",
]
