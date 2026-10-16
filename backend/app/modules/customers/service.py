"""CUSTOMERS domain service — identity resolution and CRM rules.

Every method takes the caller's session and tenant and NEVER commits: the
request/worker owns the transaction, the service owns the rules.

.. deprecated:: refactored
   Business logic now lives in ``services/customer.py``, ``services/merge.py``,
   ``services/query_360.py``, and ``services/_common.py``. This file is a
   backward-compatible aggregator that re-exports every public symbol so
   existing ``from app.modules.customers.service import X`` keeps working.
"""

from __future__ import annotations

# Re-export every public symbol from the services sub-package so all
# existing imports resolve without changes.
from app.modules.customers.services._common import (  # noqa: F401
    ISSUE_CANONICAL_COLLISION,
    ISSUE_LEGACY_DEFAULT,
    _BACKFILL_KEY,
    _ISSUE_MARK_KEYS,
    _ISSUE_RESOLUTIONS,
    _RESOLVE_ATTEMPTS,
    _canonical_or_raw,
    _contact_flag,
    _now,
    _open_contact_issues,
)
from app.modules.customers.services.customer import CustomerService  # noqa: F401
from app.modules.customers.services.merge import IdentityMergeService  # noqa: F401
from app.modules.customers.services.query_360 import Customer360Query  # noqa: F401
