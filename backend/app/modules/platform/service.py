"""PLATFORM services — jobs, notifications queue + signed outbound webhooks.

Re-export aggregator for decomposed platform services package.
"""

from __future__ import annotations

# SSRF guard re-export: the webhook tests patch the guard AT THIS MODULE (the
# aggregator is the surface the delivery tests read), and
# services/webhooks.py calls it through this module so the patch reaches the
# real call site. An earlier lint sweep removed this re-export as "dead" and
# the webhook delivery suite crashed at setup (CI 2026-10-17).
from app.core.net_guard import assert_public_url  # noqa: F401,E402
from app.modules.platform.services import (
    NOTIFICATION_STREAM,
    WEBHOOK_STREAM,
    AuditService,
    IntegrationCredentialsService,
    JobService,
    NotificationDispatcher,
    NotificationService,
    SecretService,
    WebhookDispatcher,
    WebhookService,
)

__all__ = [
    "AuditService",
    "IntegrationCredentialsService",
    "JobService",
    "NOTIFICATION_STREAM",
    "NotificationDispatcher",
    "NotificationService",
    "SecretService",
    "WEBHOOK_STREAM",
    "WebhookDispatcher",
    "WebhookService",
    "assert_public_url",
]
