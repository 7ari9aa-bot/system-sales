"""Customer services package — re-exports every public symbol."""

from app.modules.customers.services._common import (
    _BACKFILL_KEY,
    _ISSUE_MARK_KEYS,
    _ISSUE_RESOLUTIONS,
    _RESOLVE_ATTEMPTS,
    ISSUE_CANONICAL_COLLISION,
    ISSUE_LEGACY_DEFAULT,
    _canonical_or_raw,
    _contact_flag,
    _now,
    _open_contact_issues,
)
from app.modules.customers.services.customer import CustomerService
from app.modules.customers.services.merge import IdentityMergeService
from app.modules.customers.services.query_360 import Customer360Query

__all__ = [
    "CustomerService",
    "Customer360Query",
    "IdentityMergeService",
    # _common re-exports
    "ISSUE_LEGACY_DEFAULT",
    "ISSUE_CANONICAL_COLLISION",
    "_RESOLVE_ATTEMPTS",
    "_BACKFILL_KEY",
    "_ISSUE_MARK_KEYS",
    "_ISSUE_RESOLUTIONS",
    "_contact_flag",
    "_open_contact_issues",
    "_canonical_or_raw",
    "_now",
]
