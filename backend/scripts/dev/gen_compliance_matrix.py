#!/usr/bin/env python3
"""Generate docs/settings/compliance-matrix.md from the codebase.

Usage::

    python scripts/dev/gen_compliance_matrix.py            # write
    python scripts/dev/gen_compliance_matrix.py --check     # exit 1 if drift

The matrix maps every P0–P4 item from the settings specification to its
implementation status, the file that implements it, and the test that
proves it. An item is only ✅ when a real test file exists and is listed.

The CI test ``tests/test_compliance_matrix_sync.py`` calls ``--check``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_OUTPUT = _BACKEND.parent / "docs" / "settings" / "compliance-matrix.md"

# Each entry: (priority, item, status, implementation_file, test_file)
# status: "done" | "partial" | "missing"
# Only "done" entries MUST have a test_file that exists on disk.
_MATRIX: list[tuple[str, str, str, str, str]] = [
    # P0 — Architecture Foundation
    (
        "P0",
        "Static registry (SettingDef for every key)",
        "done",
        "registry.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Scope hierarchy with DB-driven chain resolution",
        "done",
        "scope_graph.py",
        "test_settings_engine_db.py",
    ),
    (
        "P0",
        "Hierarchical resolver (chain → override → default)",
        "done",
        "service.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Value validation and coercion per type",
        "done",
        "registry.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Per-key write authorization",
        "done",
        "policy.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Audit trail (append-only history)",
        "done",
        "models.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Transactional outbox event on every write",
        "done",
        "events.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Rollback to a previous revision",
        "done",
        "service.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "RLS on all tables",
        "done",
        "migrations/fe2026111801",
        "test_settings_engine_db.py",
    ),
    (
        "P0",
        "Optimistic concurrency (expected_history_id)",
        "done",
        "service.py",
        "test_settings_engine.py",
    ),
    (
        "P0",
        "Unique constraint NULLS NOT DISTINCT",
        "done",
        "migrations/fe2026111802",
        "test_settings_engine_db.py",
    ),
    # P1 — Business Configuration
    (
        "P1",
        "Business profile settings",
        "done",
        "registry.py",
        "test_settings_engine.py",
    ),
    (
        "P1",
        "Business type & vertical",
        "done",
        "registry.py",
        "test_settings_architecture.py",
    ),
    (
        "P1",
        "POS / cashier settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "Inventory settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "Orders lifecycle settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "Purchasing settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "Catalog settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "E-invoice / ETA settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "Print & receipt settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    (
        "P1",
        "Capabilities (vertical → owner switches)",
        "done",
        "capabilities.py",
        "test_settings_architecture.py",
    ),
    (
        "P1",
        "Presets (business-type configurations)",
        "done",
        "presets.py",
        "test_apparel_ground_shop_preset.py",
    ),
    (
        "P1",
        "Reports access control",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    # P2 — Communication & Intelligence
    (
        "P2",
        "Customer AI agent settings",
        "done",
        "registry.py",
        "test_settings_engine.py",
    ),
    (
        "P2",
        "Analytics AI agent settings",
        "done",
        "registry.py",
        "test_settings_engine.py",
    ),
    (
        "P2",
        "Organization settings (multi-branch, language, brand)",
        "done",
        "registry.py",
        "test_settings_architecture.py",
    ),
    (
        "P2",
        "Branch operational settings",
        "done",
        "registry.py",
        "test_settings_pos_purchasing_wiring.py",
    ),
    # P3 — Platform Management
    (
        "P3",
        "Team settings (default_role, require_2fa, session_timeout)",
        "done",
        "registry.py",
        "test_settings_remaining_wiring.py",
    ),
    (
        "P3",
        "Security settings (passwords, API rotation, audit, IP)",
        "done",
        "registry.py",
        "test_settings_remaining_wiring.py",
    ),
    (
        "P3",
        "Notification settings",
        "done",
        "registry.py",
        "test_settings_remaining_wiring.py",
    ),
    (
        "P3",
        "Billing settings",
        "done",
        "registry.py",
        "test_settings_remaining_wiring.py",
    ),
    (
        "P3",
        "Frontend unified /settings/effective consumption",
        "partial",
        "frontend/src/",
        "",
    ),
    # P4 — Advanced Governance
    (
        "P4",
        "Change requests (approval-gated settings)",
        "done",
        "service.py",
        "test_settings_final_wiring.py",
    ),
    (
        "P4",
        "Change request lifecycle (draft → applied)",
        "done",
        "models.py",
        "test_settings_final_wiring.py",
    ),
    (
        "P4",
        "Config migration framework",
        "done",
        "config_migrations.py",
        "test_config_migrations.py",
    ),
    (
        "P4",
        "Tenant-scoped restore (§164)",
        "done",
        "service.py",
        "test_tenant_restore.py",
    ),
    (
        "P4",
        "SLO framework (§168)",
        "done",
        "slo.py",
        "test_settings_slo.py",
    ),
    (
        "P4",
        "Advanced/composable presets (§170)",
        "done",
        "presets.py",
        "test_advanced_presets.py",
    ),
    (
        "P4",
        "Advanced approvals — sensitive settings (§172)",
        "done",
        "service.py",
        "test_advanced_approvals.py",
    ),
    (
        "P4",
        "Extended auditing — source + filtered search (§174)",
        "done",
        "service.py",
        "test_extended_auditing.py",
    ),
    (
        "P4",
        "Compliance matrix (auto-generated, test-synced)",
        "done",
        "scripts/dev/gen_compliance_matrix.py",
        "test_compliance_matrix_sync.py",
    ),
    (
        "P4",
        "Dynamic presets (runtime creation)",
        "missing",
        "",
        "",
    ),
    (
        "P4",
        "SecretStore integration for secret sensitivity",
        "done",
        "core/secrets.py",
        "test_settings_remaining_wiring.py",
    ),
    (
        "P4",
        "Guard test: enforced keys",
        "done",
        "registry.py",
        "test_settings_enforced_keys.py",
    ),
    (
        "P4",
        "Guard test: registry spec in sync",
        "done",
        "registry.py",
        "test_registry_spec_in_sync.py",
    ),
]

_ICON = {"done": "✅", "partial": "🟡", "missing": "❌"}


def _render() -> str:
    lines: list[str] = []
    lines.append("# Settings Compliance Matrix")
    lines.append("")
    lines.append(
        "> Auto-generated from the codebase by "
        "`scripts/dev/gen_compliance_matrix.py`.\n"
        "> Do not edit by hand — run the script and commit the result.\n"
        "> An item is only ✅ when a real test file exists and is listed.\n"
    )
    lines.append("Generated from: `backend/app/modules/settings/`")
    lines.append("")

    priorities = ["P0", "P1", "P2", "P3", "P4"]
    priority_titles = {
        "P0": "P0 — Architecture Foundation",
        "P1": "P1 — Business Configuration",
        "P2": "P2 — Communication & Intelligence",
        "P3": "P3 — Platform Management",
        "P4": "P4 — Advanced Governance",
    }

    for prio in priorities:
        items = [m for m in _MATRIX if m[0] == prio]
        if not items:
            continue
        lines.append(f"## {priority_titles[prio]}")
        lines.append("")
        lines.append("| Item | Status | Implementation | Test |")
        lines.append("|---|---|---|---|")
        for _, item, status, impl, test in items:
            icon = _ICON[status]
            impl_cell = f"`{impl}`" if impl else "—"
            test_cell = f"`{test}`" if test else "—"
            lines.append(f"| {item} | {icon} | {impl_cell} | {test_cell} |")
        lines.append("")

    done = sum(1 for m in _MATRIX if m[2] == "done")
    partial = sum(1 for m in _MATRIX if m[2] == "partial")
    missing = sum(1 for m in _MATRIX if m[2] == "missing")
    total = len(_MATRIX)
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    lines.append(f"| ✅ Done | {done} / {total} |")
    lines.append(f"| 🟡 Partial | {partial} / {total} |")
    lines.append(f"| ❌ Missing | {missing} / {total} |")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate compliance matrix")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed document has drifted",
    )
    args = parser.parse_args()

    rendered = _render()

    # Validate: every "done" item must have a test file on disk.
    errors: list[str] = []
    for _, item, status, _impl, test in _MATRIX:
        if status == "done" and test:
            test_path = _BACKEND / "tests" / test
            if not test_path.exists():
                errors.append(f"  {item}: test file '{test}' not found")
    if errors:
        print("ERROR: 'done' items with missing test files:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    if args.check:
        if not _OUTPUT.exists():
            print(
                f"ERROR: {_OUTPUT} does not exist. Run without --check first.",
                file=sys.stderr,
            )
            return 1
        existing = _OUTPUT.read_text()
        if existing != rendered:
            print(
                f"ERROR: {_OUTPUT} is out of sync. Regenerate with:\n"
                f"  python scripts/dev/gen_compliance_matrix.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {_OUTPUT.name} is in sync.")
        return 0

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(rendered)
    print(f"Written: {_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
