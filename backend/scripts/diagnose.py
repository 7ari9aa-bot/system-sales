#!/usr/bin/env python3
"""Comprehensive System Diagnostics CLI.

Runs the full-system diagnostic suite directly from terminal, printing
detailed subsystem status, response latencies, root causes, and fix steps.

Usage:
    python backend/scripts/diagnose.py
    python -m scripts.diagnose
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Add backend directory to sys.path if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.identity.models import Tenant
from app.modules.platform.diagnostics import SystemDiagnosticsService

# Terminal colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
CYAN = "\033[96m"
RESET = "\033[0m"


async def main() -> int:
    print(f"\n{BOLD}{CYAN}======================================================{RESET}")
    print(f"{BOLD}{CYAN}      نظام الفحص والتشخيص الشامل — Sales OS Diagnostics{RESET}")
    print(f"{BOLD}{CYAN}======================================================{RESET}\n")

    async with SessionLocal() as session:
        # Find default tenant or use nil UUID
        tenant = (await session.execute(select(Tenant.id).limit(1))).scalar_one_or_none()
        tenant_id = tenant or uuid.UUID("11111111-1111-1111-1111-111111111111")

        print(f"[*] جاري فحص كافة مكونات النظام والخدمات المرتبطة (Tenant: {tenant_id})...\n")

        report = await SystemDiagnosticsService.run_full_diagnostics(session, tenant_id)

    overall = report["overall_status"]
    if overall == "healthy":
        status_badge = f"{GREEN}[HEALTHY / سليم]{RESET}"
    elif overall == "degraded":
        status_badge = f"{YELLOW}[DEGRADED / تنبيه]{RESET}"
    else:
        status_badge = f"{RED}[DOWN / معطل]{RESET}"

    print(f"الحالة العامة: {status_badge}")
    print(f"ملخص الفحص:  {report['summary_ar']}\n")
    print(
        f"إجمالي الفحوصات: {report['total_checks']} | "
        f"الناجحة: {report['passed_checks']} | "
        f"المشاكل المرصودة: {report['issues_count']}\n"
    )

    print(f"{'المكون / Subsystem':<35} {'الحالة / Status':<18} {'زمن الاستجابة':<15}")
    print("-" * 72)

    has_critical = False

    for c in report["checks"]:
        st = c["status"]
        if st == "healthy":
            st_str = f"{GREEN}✓ سليم (OK){RESET}"
        elif st == "degraded":
            st_str = f"{YELLOW}⚠ تنبيه (Degraded){RESET}"
        else:
            st_str = f"{RED}✗ معطل (Down){RESET}"
            has_critical = True

        lat_str = f"{c['latency_ms']} ms" if c.get("latency_ms") is not None else "—"
        name = f"{c['name_ar']} ({c['name_en']})"
        if len(name) > 33:
            name = name[:30] + "..."

        print(f"{name:<35} {st_str:<28} {lat_str:<15}")

        # If there is root cause or error, print details cleanly
        if c.get("root_cause") or c.get("error"):
            if c.get("error"):
                print(f"  {RED}↳ الخطأ التقني:{RESET} {c['error']}")
            if c.get("root_cause"):
                print(f"  {YELLOW}↳ السبب الجذري الدقيق:{RESET} {c['root_cause']}")
            if c.get("remediation"):
                print(f"  {CYAN}↳ الإجراء المقترح للإصلاح:{RESET} {c['remediation']}")
            print()

    print(f"\n{BOLD}{CYAN}======================================================{RESET}\n")

    return 1 if has_critical else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
