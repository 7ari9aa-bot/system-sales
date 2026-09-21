"""NOTIFICATIONS domain models.

In-app notification rows — re-exported from platform domain.
§166: NotificationPreference — per-user channel preferences + quiet hours.
"""
from __future__ import annotations

from app.modules.platform.models import Notification, NotificationPreference

__all__ = ["Notification", "NotificationPreference"]
