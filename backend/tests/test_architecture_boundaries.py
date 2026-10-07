"""§138 — Architecture boundary enforcement tests.

A module MUST NOT access another module's repository directly (§8).
These tests scan import statements to catch violations at CI time.

We check BOTH top-level and lazy (function-scope) imports — a lazy import
of another module's models is still a boundary violation.
"""

import ast
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / "app" / "modules"
SERVICE_FILES = sorted(MODULES_DIR.glob("*/service.py"))

# Modules that are allowed to import their own models — these are
# cross-cutting infrastructure modules whose models are shared contracts
# (audit log, security events, tenant/user). They are NOT domain modules
# with private repositories.
# This list will shrink as we extract proper service contracts for them.
_ALLOWED_CROSS_MODULE = {
    "platform",  # AuditLog, SecurityEvent — shared infrastructure
    "identity",  # Tenant, User — shared identity model
}


def _extract_cross_module_model_imports(file_path: Path) -> list[str]:
    """Return all 'from app.modules.<X>.models import ...' where X != owning module.

    Checks BOTH top-level and function-scope (lazy) imports.
    Excludes cross-cutting infrastructure modules in _ALLOWED_CROSS_MODULE.
    """
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    owning_module = file_path.parent.name
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("app.modules.") and module.endswith(".models"):
                parts = module.split(".")
                source_module = parts[2] if len(parts) > 2 else None
                if source_module and source_module != owning_module:
                    # Skip cross-cutting infrastructure modules
                    if source_module in _ALLOWED_CROSS_MODULE:
                        continue
                    violations.append(module)
    return violations


def test_orders_does_not_import_other_module_models():
    """§8: orders/service.py must not import catalog.models or inventory.models."""
    file = MODULES_DIR / "orders" / "service.py"
    violations = _extract_cross_module_model_imports(file)
    assert violations == [], f"orders/service.py imports other module models: {violations}"


def test_conversations_does_not_import_customers_models():
    """§8: conversations/service.py must not import customers.models."""
    file = MODULES_DIR / "conversations" / "service.py"
    violations = _extract_cross_module_model_imports(file)
    assert violations == [], f"conversations/service.py imports other module models: {violations}"


def test_inventory_does_not_import_catalog_models():
    """§8: inventory/service.py must not import catalog.models."""
    file = MODULES_DIR / "inventory" / "service.py"
    violations = _extract_cross_module_model_imports(file)
    assert violations == [], f"inventory/service.py imports other module models: {violations}"


def test_no_domain_service_imports_other_module_models():
    """§8: No domain service.py may import another domain module's .models directly.

    Cross-cutting infrastructure modules (platform, identity) are exempt —
    their models are shared contracts, not private repositories. This exemption
    will be removed once proper service contracts are extracted.
    """
    all_violations: dict[str, list[str]] = {}
    for file in SERVICE_FILES:
        owning_module = file.parent.name
        if owning_module in _ALLOWED_CROSS_MODULE:
            continue
        violations = _extract_cross_module_model_imports(file)
        if violations:
            all_violations[str(file.relative_to(MODULES_DIR))] = violations
    assert not all_violations, f"Cross-module model import violations: {all_violations}"
