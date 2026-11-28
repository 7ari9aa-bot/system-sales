#!/usr/bin/env python3
"""Generate docs/settings/registry-specification.md from registry.py.

Usage::

    python scripts/dev/gen_registry_spec.py            # write to docs/settings/
    python scripts/dev/gen_registry_spec.py --check     # exit 1 if docs drift

The script imports the live registry and renders one markdown table per domain.
Run it whenever ``registry.py`` changes and commit the result. The CI test
``tests/test_registry_spec_in_sync.py`` calls ``--check`` to fail CI if the
committed document no longer matches the code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── bootstrap: make ``app.*`` importable when run from the backend dir ──
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.platform.settings.registry import (  # noqa: E402
    REGISTRY,
    domains,
    list_definitions,
)

_OUTPUT = _BACKEND.parent / "docs" / "settings" / "registry-specification.md"

_DASH = "—"

_DOMAIN_TITLES: dict[str, str] = {
    "business": "Business & Shop Profile",
    "pos": "POS / Cashier",
    "einvoice": "E-Invoice / ETA",
    "inventory": "Inventory",
    "orders": "Orders",
    "purchasing": "Purchasing",
    "print": "Print & Barcode",
    "notifications": "Notifications",
    "customer_agent": "Customer AI Agent",
    "analytics_agent": "Analytics Agent",
    "organization": "Organization",
    "branch": "Branch",
    "catalog": "Catalog",
    "team": "Team",
    "security": "Security",
    "billing": "Billing",
    "reports": "Reports",
    "imports": "Imports",
}


def _fmt_default(val: object) -> str:
    """Render a default value for the table cell."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return f"`{val}`" if val else '`""`'
    if isinstance(val, list):
        if not val:
            return "`[]`"
        inner = ", ".join(str(v) for v in val)
        return f"`[{inner}]`"
    return f"`{val!r}`"


def _fmt_scopes(defn) -> str:
    return ", ".join(s.value.upper() for s in defn.scopes)


def _fmt_min_max(defn) -> tuple[str, str]:
    mn = _DASH if defn.min_value is None else str(defn.min_value)
    mx = _DASH if defn.max_value is None else str(defn.max_value)
    return mn, mx


def _fmt_allowed(defn) -> str:
    if defn.allowed_values:
        return ", ".join(defn.allowed_values)
    return _DASH


def _fmt_segments(defn) -> str:
    if not defn.segments:
        return "all"
    return ", ".join(defn.segments)


def _fmt_enforced(defn) -> str:
    return "✅" if defn.enforced else "—"


def _render_domain(domain: str, defs: list) -> list[str]:
    """Render one domain section as a list of markdown lines."""
    title = _DOMAIN_TITLES.get(domain, domain.replace("_", " ").title())
    lines: list[str] = []
    lines.append(f"## {title} ({len(defs)} settings)")
    lines.append("")
    lines.append(
        "| Key | Type | Default | Scopes | Sens. | Apply | Min | Max "
        "| Enforced | Allowed | Segments |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for d in defs:
        mn, mx = _fmt_min_max(d)
        lines.append(
            f"| `{d.key}` | {d.type.value} | {_fmt_default(d.default)} "
            f"| {_fmt_scopes(d)} | {d.sensitivity.value} | {d.apply_mode.value} "
            f"| {mn} | {mx} | {_fmt_enforced(d)} | {_fmt_allowed(d)} "
            f"| {_fmt_segments(d)} |"
        )
    lines.append("")
    return lines


def generate() -> str:
    """Return the full markdown document as a string."""
    total = len(REGISTRY)
    domain_names = domains()

    lines: list[str] = []
    lines.append("# Settings Registry Specification")
    lines.append("")
    lines.append(
        f"> Source of truth: `backend/app/platform/settings/registry.py` — {total} settings."
    )
    lines.append(
        "> This document is **generated** from the code by "
        "`backend/scripts/dev/gen_registry_spec.py`."
    )
    lines.append(
        "> If the code and this table disagree, the code wins; run the script to regenerate."
    )
    lines.append("")

    lines.append("## How to read this table")
    lines.append("")
    lines.append("| Column | Meaning |")
    lines.append("|---|---|")
    lines.append("| **Key** | Dotted identifier used in code and API |")
    lines.append("| **Type** | `bool`, `number`, `string`, `enum`, `list` |")
    lines.append("| **Default** | Factory value when no override exists at any scope |")
    lines.append("| **Scopes** | Which scopes may override (first = lowest meaningful) |")
    lines.append("| **Sens.** | `normal`, `sensitive`, or `secret` |")
    lines.append("| **Apply** | `immediate`, `validated`, or `approval_required` |")
    lines.append("| **Min / Max** | Numeric bounds (— = unbounded) |")
    lines.append("| **Enforced** | ✅ if a service actually reads this key (in `ENFORCED_KEYS`) |")
    lines.append("| **Allowed** | For `enum` types: the set of valid values (— = n/a) |")
    lines.append("| **Segments** | Business types this applies to (`all` = every segment) |")
    lines.append("")

    lines.append(
        "All overrides are stored in the `tenant_settings` table (tenant-scoped, RLS-protected). "
        "History is in `tenant_settings_history` (append-only). "
        "Approval flows use `setting_change_requests`."
    )
    lines.append("")

    lines.append("---")
    lines.append("")

    for domain in domain_names:
        defs = list_definitions(domain=domain)
        lines.extend(_render_domain(domain, defs))

    lines.append("---")
    lines.append("")
    lines.append("## Scope inheritance chain")
    lines.append("")
    lines.append("```")
    lines.append("TENANT → WORKSPACE → BRANCH → WAREHOUSE → POS_PROFILE → REGISTER")
    lines.append("TENANT → CHANNEL")
    lines.append("TENANT → USER")
    lines.append("```")
    lines.append("")

    # Capabilities section
    lines.append("## Capabilities (owner switches)")
    lines.append("")
    lines.append(
        "Each capability is a `capability.<name>` setting (domain `business`, type `bool`). "
        "The vertical picks the starting answer; the owner's override wins."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate registry specification markdown")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed document differs from the generated one",
    )
    args = parser.parse_args()

    content = generate()

    if args.check:
        if not _OUTPUT.exists():
            print(f"ERROR: {_OUTPUT} does not exist. Run gen_registry_spec.py to create it.")
            return 1
        existing = _OUTPUT.read_text(encoding="utf-8")
        if existing.strip() != content.strip():
            print(f"ERROR: {_OUTPUT} is out of sync with registry.py.")
            print("Run: python scripts/dev/gen_registry_spec.py")
            return 1
        print(f"OK: {_OUTPUT} matches registry.py ({len(REGISTRY)} settings).")
        return 0

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(content + "\n", encoding="utf-8")
    print(f"Wrote {_OUTPUT} ({len(REGISTRY)} settings).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
