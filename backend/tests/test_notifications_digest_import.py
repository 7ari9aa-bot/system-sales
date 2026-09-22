"""Import-safety guard for ``app.modules.notifications.digest`` (Wave 0, W0.3).

``digest.py`` re-declared ``__tablename__ = "notification_preferences"`` while
the canonical ``NotificationPreference`` already lives in
``app.modules.platform.models``. The module is dead code today (nothing imports
it), so the SQLAlchemy table-redefinition error was latent: the first import of
``digest`` alongside the canonical model would raise
``sqlalchemy.exc.InvalidRequestError`` ("Table 'notification_preferences' is
already defined for this MetaData instance") and could break app startup.

The fix deleted the duplicate class and binds the canonical model instead.
This test pins both halves of that contract:

1. importing ``app.modules.notifications.digest`` next to the canonical model
   does not raise, and
2. ``digest.NotificationPreference`` IS the canonical class (identity), while
   ``NotificationDigest`` / ``NotificationAggregator`` stay in place for the
   Wave 4 (§166) wiring.

DB-free: pure import + identity assertions, so it runs locally and in CI.
"""

from __future__ import annotations

# The table collision is symmetric: whichever module declares
# "notification_preferences" second raises, so import order here does not
# matter — conftest already pulls the platform model graph in regardless.
from app.modules.notifications import digest
from app.modules.platform import models as platform_models


def test_digest_module_exposes_the_canonical_notification_preference() -> None:
    """``digest.NotificationPreference`` is the platform model, not a re-declaration."""
    assert digest.NotificationPreference is platform_models.NotificationPreference
    assert platform_models.NotificationPreference.__tablename__ == "notification_preferences"


def test_digest_module_keeps_digest_and_aggregator_for_wave_4() -> None:
    """NotificationDigest / NotificationAggregator are retained (wired in Wave 4, §166)."""
    assert digest.NotificationDigest.__tablename__ == "notification_digests"
    assert hasattr(digest.NotificationAggregator, "should_send_immediately")
    assert hasattr(digest.NotificationAggregator, "add_to_digest")
