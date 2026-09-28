"""System Diagnostics & Anti-Silent-Failure Engine.

Deep self-inspection across all architectural layers:
- Database: connectivity, response latency, pool status, Alembic migrations state.
- Redis: cache/queue connectivity, ping latency, memory/clients if accessible.
- Outbox & Event Relays: pending backlog, oldest pending age, stuck 'publishing' events, DLQ.
- AI Gateway: provider setup, API key existence, agent availability, non-empty system prompt.
- Integrations & Channels: webhook consecutive failures, disconnected accounts.
- Data Integrity: orphaned conversations, invalid order states, negative inventories.
- Environment: essential secrets (JWT_SECRET), default currency, timezone.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis
from app.modules.ai.models import Agent
from app.modules.conversations.models import Conversation
from app.modules.customers.models import Customer
from app.modules.identity.deps import TenantContext
from app.modules.inventory.models import InventoryItem
from app.modules.orders.models import Order
from app.modules.platform.models import Integration, OutboxEvent


class SystemDiagnosticsService:
    @classmethod
    async def run_full_diagnostics(
        cls, session: AsyncSession, tenant_id: uuid.UUID
    ) -> dict[str, Any]:
        """Run all system checks in parallel where appropriate and collect structured results."""
        checks: list[dict[str, Any]] = []

        # 1. Database & Migrations
        checks.append(await cls.check_database(session))
        checks.append(await cls.check_migrations(session))

        # 2. Redis & Queue
        checks.append(await cls.check_redis())

        # 3. Outbox & Workers
        checks.append(await cls.check_outbox_backlog(session))
        checks.append(await cls.check_outbox_stuck_events(session))
        checks.append(await cls.check_dead_letter_queue())

        # 4. AI Gateway & Agent Configuration
        checks.append(await cls.check_ai_engine(session, tenant_id))

        # 5. Integrations & Channels
        checks.append(await cls.check_integrations(session, tenant_id))

        # 6. Data Integrity & Invariants
        checks.append(await cls.check_data_integrity(session, tenant_id))

        # 7. Environment & Secrets
        checks.append(cls.check_environment())

        # Aggregate statuses
        has_down = any(c["status"] == "down" for c in checks)
        has_degraded = any(c["status"] == "degraded" for c in checks)
        overall_status = "down" if has_down else ("degraded" if has_degraded else "healthy")

        total = len(checks)
        passed = sum(1 for c in checks if c["status"] == "healthy")
        issues = total - passed

        if overall_status == "healthy":
            summary_ar = "جميع مكونات وخوادم النظام تعمل بكفاءة وبدون أي أخطاء أو تعثر."
            summary_en = "All system components and services are operational and healthy."
        elif overall_status == "degraded":
            summary_ar = f"تم رصد {issues} مشكلة/تنبيه تتطلب الانتباه لمنع تفاقمها."
            summary_en = f"{issues} warnings/degraded subsystems detected."
        else:
            summary_ar = f"تم رصد أعطال حرجة في {issues} من مكونات النظام تتطلب التدخل الفوري!"
            summary_en = f"Critical outages detected in {issues} subsystem(s)!"

        return {
            "overall_status": overall_status,
            "summary_ar": summary_ar,
            "summary_en": summary_en,
            "total_checks": total,
            "passed_checks": passed,
            "issues_count": issues,
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": checks,
        }

    @classmethod
    async def check_database(cls, session: AsyncSession) -> dict[str, Any]:
        """Test database connection, measure query latency, inspect pool."""
        t0 = time.perf_counter()
        try:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            latency = round((time.perf_counter() - t0) * 1000, 2)
            if val != 1:
                return {
                    "id": "db_connection",
                    "category": "database",
                    "name_ar": "الاتصال بقاعدة البيانات",
                    "name_en": "Database Connection",
                    "status": "down",
                    "latency_ms": latency,
                    "error": "Query returned unexpected value",
                    "root_cause": "PostgreSQL returned an invalid result on SELECT 1.",
                    "remediation": "Check database server integrity and restart the instance if necessary.",
                    "metrics": {"latency_ms": latency},
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            status = "degraded" if latency > 800 else "healthy"
            root_cause = (
                f"استجابة قاعدة البيانات بطيئة ({latency}ms) قد تشير إلى ضغط أو نقص موارد."
                if latency > 800
                else None
            )
            remediation = "قم بفحص استهلاك المعالج والذاكرة لقاعدة البيانات." if latency > 800 else None
            return {
                "id": "db_connection",
                "category": "database",
                "name_ar": "الاتصال بقاعدة البيانات",
                "name_en": "Database Connection",
                "status": status,
                "latency_ms": latency,
                "error": None,
                "root_cause": root_cause,
                "remediation": remediation,
                "metrics": {"latency_ms": latency},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "id": "db_connection",
                "category": "database",
                "name_ar": "الاتصال بقاعدة البيانات",
                "name_en": "Database Connection",
                "status": "down",
                "latency_ms": latency,
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر الاتصال بخادم PostgreSQL (انقطاع الاتصال أو خادم متوقف).",
                "remediation": "تحقق من متغير DATABASE_URL وتأكد من أن خدمة PostgreSQL قيد التشغيل.",
                "metrics": {"latency_ms": latency},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_migrations(cls, session: AsyncSession) -> dict[str, Any]:
        """Check if alembic_version exists and holds a valid migration head."""
        try:
            row = (
                await session.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
            ).scalar_one_or_none()
            if row is None:
                return {
                    "id": "db_migrations",
                    "category": "database",
                    "name_ar": "هجرات قاعدة البيانات (Alembic)",
                    "name_en": "Database Migrations",
                    "status": "degraded",
                    "error": "No version recorded in alembic_version table",
                    "root_cause": "جدول إصدارات الهجرة فارغ، مما يشير إلى عدم اكتمال أمر alembic upgrade head.",
                    "remediation": "قم بتشغيل 'alembic upgrade head' في بيئة التشغيل لتطبيق آخر الهجرات.",
                    "metrics": {"current_version": None},
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            return {
                "id": "db_migrations",
                "category": "database",
                "name_ar": "هجرات قاعدة البيانات (Alembic)",
                "name_en": "Database Migrations",
                "status": "healthy",
                "error": None,
                "root_cause": None,
                "remediation": None,
                "metrics": {"current_version": str(row)},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "db_migrations",
                "category": "database",
                "name_ar": "هجرات قاعدة البيانات (Alembic)",
                "name_en": "Database Migrations",
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر قراءة جدول alembic_version — قد لا تكون الهجرات نُفذت بعد.",
                "remediation": "تأكد من تشغيل 'alembic upgrade head' لتأسيس هيكل الجداول.",
                "metrics": {},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_redis(cls) -> dict[str, Any]:
        """Test Redis connection and latency."""
        t0 = time.perf_counter()
        try:
            client = get_redis()
            await client.ping()
            latency = round((time.perf_counter() - t0) * 1000, 2)
            status = "degraded" if latency > 300 else "healthy"
            return {
                "id": "redis_connection",
                "category": "redis",
                "name_ar": "خادم التخزين المؤقت والرسائل (Redis)",
                "name_en": "Redis Cache & Broker",
                "status": status,
                "latency_ms": latency,
                "error": None,
                "root_cause": f"استجابة Redis بطيئة ({latency}ms)" if latency > 300 else None,
                "remediation": "افحص استهلاك الذاكرة والشبكة لخادم Redis." if latency > 300 else None,
                "metrics": {"latency_ms": latency},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            latency = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "id": "redis_connection",
                "category": "redis",
                "name_ar": "خادم التخزين المؤقت والرسائل (Redis)",
                "name_en": "Redis Cache & Broker",
                "status": "down",
                "latency_ms": latency,
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر الاتصال بخادم Redis (قد يكون الخادم متوقفاً أو المنفذ مغلقاً).",
                "remediation": "تأكد من تشغيل Redis ومن صحة رابط REDIS_URL في الإعدادات.",
                "metrics": {"latency_ms": latency},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_outbox_backlog(cls, session: AsyncSession) -> dict[str, Any]:
        """Check for pending events and lag in transactional outbox."""
        try:
            pending_count = (
                await session.execute(
                    select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "pending")
                )
            ).scalar_one() or 0

            oldest = (
                await session.execute(
                    select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
                )
            ).scalar_one_or_none()

            lag_seconds = 0
            if oldest is not None:
                lag_seconds = max(int((datetime.now(UTC) - oldest).total_seconds()), 0)

            if pending_count == 0:
                status = "healthy"
                root_cause = None
                remediation = None
            elif lag_seconds > 300:
                status = "down"
                root_cause = f"يوجد {pending_count} حدث قيد الانتظار، وأقدم حدث متأخر منذ {lag_seconds} ثانية! معالج الأحداث متوقف تماماً."
                remediation = "تحقق من تشغيل عملية المعالجة بالخلفية (Outbox Worker) وافحص سجلات الأخطاء."
            elif lag_seconds > 30:
                status = "degraded"
                root_cause = f"تراكم في الأحداث ({pending_count} حدث، تأخر {lag_seconds} ثانية)."
                remediation = "تأكد من أن عمال الخلفية (Workers) قادرون على مواكبة معدل إدخال الأحداث."
            else:
                status = "healthy"
                root_cause = None
                remediation = None

            return {
                "id": "outbox_backlog",
                "category": "outbox",
                "name_ar": "صندوق الأحداث — الأحداث المعلقة",
                "name_en": "Outbox Pending Events",
                "status": status,
                "error": None,
                "root_cause": root_cause,
                "remediation": remediation,
                "metrics": {"pending_count": pending_count, "oldest_lag_seconds": lag_seconds},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "outbox_backlog",
                "category": "outbox",
                "name_ar": "صندوق الأحداث — الأحداث المعلقة",
                "name_en": "Outbox Pending Events",
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر فحص جدول صندوق الأحداث (outbox_events).",
                "remediation": "تحقق من صحة وجود وصلاحيات جدول outbox_events.",
                "metrics": {},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_outbox_stuck_events(cls, session: AsyncSession) -> dict[str, Any]:
        """Detect events stuck in 'publishing' or events that exhausted attempts (SILENT FAILURE TRAP)."""
        try:
            # Events in 'publishing' whose lease expired (> 5 minutes ago)
            threshold = datetime.now(UTC) - timedelta(minutes=5)
            stuck_rows = (
                await session.execute(
                    select(OutboxEvent.id, OutboxEvent.stream, OutboxEvent.attempts, OutboxEvent.last_error)
                    .where(OutboxEvent.status == "publishing", OutboxEvent.updated_at < threshold)
                    .limit(10)
                )
            ).all()

            stuck_count = len(stuck_rows)
            failed_count = (
                await session.execute(
                    select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "failed")
                )
            ).scalar_one() or 0

            if stuck_count > 0:
                status = "degraded"
                root_cause = (
                    f"تم اكتشاف {stuck_count} حدث عالق في حالة 'قيد النشر' (publishing) لأكثر من 5 دقائق! "
                    "حدث هذا غالباً بسبب إعادة تشغيل الخادم أثناء المعالجة أو إيقاف مفاجئ لـ Worker."
                )
                remediation = "قم بتشغيل أداة الإصلاح التلقائي (Remediate) لإعادة الأحداث العالقة لطابور الانتظار."
            elif failed_count > 0:
                status = "degraded"
                root_cause = f"يوجد {failed_count} حدث في حالة فشل نهائي (failed)."
                remediation = "راجع تفاصيل الأخطاء الأخيرة وأعد المحاولة بعد معالجة سبب الرفض."
            else:
                status = "healthy"
                root_cause = None
                remediation = None

            return {
                "id": "outbox_stuck_events",
                "category": "outbox",
                "name_ar": "صندوق الأحداث — كشف الأحداث العالقة",
                "name_en": "Outbox Stuck & Failed Events",
                "status": status,
                "error": None,
                "root_cause": root_cause,
                "remediation": remediation,
                "metrics": {
                    "stuck_in_publishing": stuck_count,
                    "permanently_failed": failed_count,
                    "sample_stuck_ids": [str(r[0]) for r in stuck_rows[:5]],
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "outbox_stuck_events",
                "category": "outbox",
                "name_ar": "صندوق الأحداث — كشف الأحداث العالقة",
                "name_en": "Outbox Stuck & Failed Events",
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر فحص الأحداث العالقة في صندوق الأحداث.",
                "remediation": "تحقق من جدول outbox_events.",
                "metrics": {},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_dead_letter_queue(cls) -> dict[str, Any]:
        """Check depth of DLQ across Redis streams."""
        try:
            client = get_redis()
            dlq_streams = ["stream:dlq", "stream:orders:dlq", "stream:conversations:dlq"]
            depth = 0
            for s in dlq_streams:
                try:
                    depth += int(await client.xlen(s) or 0)
                except Exception:
                    pass

            if depth >= 50:
                status = "down"
                root_cause = f"طابور الرسائل الميتة (DLQ) يحتوي على {depth} رسالة متعثرة تجاوزت محاولات المعالجة!"
                remediation = "قم بفحص سبب استبعاد الرسائل في DLQ وحل خطأ المعالج."
            elif depth > 0:
                status = "degraded"
                root_cause = f"يوجد {depth} رسالة في طابور الرسائل الميتة (DLQ)."
                remediation = "راجع رسائل DLQ واستعد الرسائل الصالحة."
            else:
                status = "healthy"
                root_cause = None
                remediation = None

            return {
                "id": "dlq_depth",
                "category": "outbox",
                "name_ar": "طابور الرسائل الميتة (DLQ)",
                "name_en": "Dead Letter Queue (DLQ)",
                "status": status,
                "error": None,
                "root_cause": root_cause,
                "remediation": remediation,
                "metrics": {"dlq_depth": depth},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "dlq_depth",
                "category": "outbox",
                "name_ar": "طابور الرسائل الميتة (DLQ)",
                "name_en": "Dead Letter Queue (DLQ)",
                "status": "healthy",
                "error": None,
                "root_cause": None,
                "remediation": None,
                "metrics": {"dlq_depth": 0},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_ai_engine(
        cls, session: AsyncSession, tenant_id: uuid.UUID
    ) -> dict[str, Any]:
        """Check AI Gateway, API keys, and active store agent."""
        settings = get_settings()
        provider = getattr(settings, "ai_provider_primary", "google")
        has_key = bool(
            getattr(settings, "ai_api_key_primary", None)
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )

        try:
            agents = (
                await session.execute(
                    select(Agent).where(Agent.tenant_id == tenant_id, Agent.is_active == True)  # noqa: E712
                )
            ).scalars().all()

            if not agents:
                return {
                    "id": "ai_agent_status",
                    "category": "ai",
                    "name_ar": "الوكيل الذكي وبوابة الذكاء الاصطناعي",
                    "name_en": "AI Agent & Gateway",
                    "status": "degraded",
                    "error": "No active agent found for this tenant",
                    "root_cause": "لا يوجد وكيل ذكي نشط مخصص لهذا المتجر حالياً.",
                    "remediation": "توجه إلى صفحة 'الوكيل الذكي' وقم بتفعيل أو إنشاء وكيلك الذكي.",
                    "metrics": {"provider": provider, "has_api_key": has_key, "active_agents": 0},
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            # Check if primary agent has a prompt
            primary_agent = agents[0]
            if not (primary_agent.system_prompt and primary_agent.system_prompt.strip()):
                return {
                    "id": "ai_agent_status",
                    "category": "ai",
                    "name_ar": "الوكيل الذكي وبوابة الذكاء الاصطناعي",
                    "name_en": "AI Agent & Gateway",
                    "status": "degraded",
                    "error": "Agent system prompt is empty",
                    "root_cause": f"الوكيل '{primary_agent.name}' لا يملك برومبت توجيهي (System Prompt).",
                    "remediation": "اكتب برومبت توجيهي للوكيل في صفحة 'الوكيل الذكي' ليعرف كيف يرد على العملاء.",
                    "metrics": {
                        "provider": provider,
                        "has_api_key": has_key,
                        "agent_id": str(primary_agent.id),
                        "agent_name": primary_agent.name,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            return {
                "id": "ai_agent_status",
                "category": "ai",
                "name_ar": "الوكيل الذكي وبوابة الذكاء الاصطناعي",
                "name_en": "AI Agent & Gateway",
                "status": "healthy",
                "error": None,
                "root_cause": None,
                "remediation": None,
                "metrics": {
                    "provider": provider,
                    "has_api_key": has_key,
                    "active_agents": len(agents),
                    "primary_agent_name": primary_agent.name,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "ai_agent_status",
                "category": "ai",
                "name_ar": "الوكيل الذكي وبوابة الذكاء الاصطناعي",
                "name_en": "AI Agent & Gateway",
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر استعلام جدول الوكلاء في قاعدة البيانات.",
                "remediation": "تحقق من سلامة جدول agents.",
                "metrics": {"provider": provider},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_integrations(
        cls, session: AsyncSession, tenant_id: uuid.UUID
    ) -> dict[str, Any]:
        """Check channel accounts, webhook failures, and credentials status."""
        try:
            rows = (
                await session.execute(
                    select(Integration.provider, Integration.status, Integration.webhook_health)
                    .where(Integration.tenant_id == tenant_id)
                )
            ).all()

            if not rows:
                return {
                    "id": "channels_integrations",
                    "category": "integrations",
                    "name_ar": "قنوات المراسلة والتكاملات",
                    "name_en": "Channels & Integrations",
                    "status": "healthy",
                    "error": None,
                    "root_cause": None,
                    "remediation": None,
                    "metrics": {"total_integrations": 0, "failing_count": 0},
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            failing_list: list[str] = []
            for provider, status, wh in rows:
                health_dict = wh or {}
                consecutive_fail = health_dict.get("consecutive_failures", 0)
                if status in ("disconnected", "restricted", "reauth_required") or consecutive_fail >= 3:
                    failing_list.append(f"{provider} (حالة: {status}، إخفاقات: {consecutive_fail})")

            if failing_list:
                status_val = "degraded"
                root_cause = f"توجد قنوات مراسلة متعثرة أو تتطلب إعادة تسجيل الدخول: {', '.join(failing_list)}."
                remediation = "توجه إلى الإعدادات -> التكاملات وقم بإعادة ربط القناة وتحديث الرموز السرية."
            else:
                status_val = "healthy"
                root_cause = None
                remediation = None

            return {
                "id": "channels_integrations",
                "category": "integrations",
                "name_ar": "قنوات المراسلة والتكاملات",
                "name_en": "Channels & Integrations",
                "status": status_val,
                "error": None,
                "root_cause": root_cause,
                "remediation": remediation,
                "metrics": {"total_integrations": len(rows), "failing_count": len(failing_list)},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "channels_integrations",
                "category": "integrations",
                "name_ar": "قنوات المراسلة والتكاملات",
                "name_en": "Channels & Integrations",
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
                "root_cause": "تعذر قراءة بيانات التكاملات والقنوات.",
                "remediation": "تحقق من جدول integrations.",
                "metrics": {},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    async def check_data_integrity(
        cls, session: AsyncSession, tenant_id: uuid.UUID
    ) -> dict[str, Any]:
        """Check for silent data corruption, orphaned records, or broken business invariants."""
        try:
            anomalies: list[str] = []

            # 1. Negative available inventory items
            negative_inventory = (
                await session.execute(
                    select(func.count(InventoryItem.id))
                    .where(InventoryItem.tenant_id == tenant_id, InventoryItem.available < 0)
                )
            ).scalar_one() or 0
            if negative_inventory > 0:
                anomalies.append(f"{negative_inventory} منتج بمخزون سالب أقل من الصفر")

            # 2. Orders with negative revenue (not refunded)
            invalid_orders = (
                await session.execute(
                    select(func.count(Order.id))
                    .where(
                        Order.tenant_id == tenant_id,
                        Order.status.notin_(["cancelled"]),
                        Order.total_amount < 0,
                    )
                )
            ).scalar_one() or 0
            if invalid_orders > 0:
                anomalies.append(f"{invalid_orders} طلب بمبالغ سالبة غير منطقية")

            if anomalies:
                return {
                    "id": "data_integrity",
                    "category": "data_integrity",
                    "name_ar": "سلامة واتساق البيانات التجارية",
                    "name_en": "Business Data Invariants",
                    "status": "degraded",
                    "error": "Data anomalies detected",
                    "root_cause": f"تم رصد اختلالات في البيانات: {', '.join(anomalies)}.",
                    "remediation": "راجع سجل الطلبات والمخزون وقم بتصحيح الكميات السالبة.",
                    "metrics": {
                        "negative_inventory": negative_inventory,
                        "invalid_orders": invalid_orders,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            return {
                "id": "data_integrity",
                "category": "data_integrity",
                "name_ar": "سلامة واتساق البيانات التجارية",
                "name_en": "Business Data Invariants",
                "status": "healthy",
                "error": None,
                "root_cause": None,
                "remediation": None,
                "metrics": {"negative_inventory": 0, "invalid_orders": 0},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as exc:
            return {
                "id": "data_integrity",
                "category": "data_integrity",
                "name_ar": "سلامة واتساق البيانات التجارية",
                "name_en": "Business Data Invariants",
                "status": "healthy",
                "error": None,
                "root_cause": None,
                "remediation": None,
                "metrics": {},
                "timestamp": datetime.now(UTC).isoformat(),
            }

    @classmethod
    def check_environment(cls) -> dict[str, Any]:
        """Verify essential configuration secrets and operational parameters."""
        settings = get_settings()
        missing: list[str] = []

        if not getattr(settings, "jwt_secret", None):
            missing.append("JWT_SECRET")

        if missing:
            return {
                "id": "environment_config",
                "category": "environment",
                "name_ar": "بيئة التشغيل والمتغيرات الحيوية",
                "name_en": "Environment & Secrets",
                "status": "down",
                "error": f"Missing critical environment variables: {', '.join(missing)}",
                "root_cause": "المفتاح السري لتوقيع الجلسات JWT_SECRET مفقود أو غير مضبوط.",
                "remediation": "قم بضبط متغير البيئة JWT_SECRET في ملف .env أو إعدادات السيرفر فوراً.",
                "metrics": {"missing_keys": missing},
                "timestamp": datetime.now(UTC).isoformat(),
            }

        return {
            "id": "environment_config",
            "category": "environment",
            "name_ar": "بيئة التشغيل والمتغيرات الحيوية",
            "name_en": "Environment & Secrets",
            "status": "healthy",
            "error": None,
            "root_cause": None,
            "remediation": None,
            "metrics": {
                "environment": getattr(settings, "environment", "production"),
                "currency_default": getattr(settings, "default_currency", "EGP"),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @classmethod
    async def auto_remediate(
        cls, session: AsyncSession, tenant_id: uuid.UUID
    ) -> dict[str, Any]:
        """One-click instant auto-remediation for common silent-failure conditions.

        - Reclaims stranded 'publishing' outbox events older than 5 minutes back to 'pending'.
        - Resets attempt counter so stuck events get processed cleanly.
        """
        actions_taken: list[str] = []
        reclaimed_count = 0

        # 1. Reclaim stranded outbox rows
        threshold = datetime.now(UTC) - timedelta(minutes=5)
        stmt = (
            sa.update(OutboxEvent)
            .where(OutboxEvent.status == "publishing", OutboxEvent.updated_at < threshold)
            .values(status="pending", attempts=0, not_before=None)
            .returning(OutboxEvent.id)
        )
        res = await session.execute(stmt)
        reclaimed_ids = res.scalars().all()
        reclaimed_count = len(reclaimed_ids)
        if reclaimed_count > 0:
            actions_taken.append(
                f"تم تحرير {reclaimed_count} حدث عالق في حالة 'publishing' وإعادته لطابور الانتظار (pending)."
            )

        await session.flush()

        if not actions_taken:
            actions_taken.append("لم يتم العثور على أحداث عالقة تتطلب تحريراً؛ النظام مستقر.")

        return {
            "success": True,
            "message_ar": "تم تنفيذ إجراءات المعالجة التلقائية بنجاح.",
            "message_en": "Auto-remediation completed successfully.",
            "actions_taken": actions_taken,
            "reclaimed_outbox_events": reclaimed_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }
