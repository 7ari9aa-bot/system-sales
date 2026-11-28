"""FIHRIST Apparel must be a real application, not a declared one.

Every name the manifest publishes is checked against code that exists: a
module's backend packages, its permission codes, its screens, and the settings
domains the registry actually uses. A manifest that drifts from the code is how
an architecture document becomes fiction (industry-applications §14).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.applications.apparel.manifest import APP_MANIFEST, MODULES, module_keys
from app.applications.apparel.permissions import NAMESPACE, PERMISSIONS, codes_for_module
from app.applications.apparel.routes import PREFIX, ROUTES, SHELL, legacy_paths, routes_for_module
from app.applications.apparel.settings_ownership import (
    PLATFORM_SETTINGS_DOMAINS,
    owned_settings_domains,
    owner_of,
)
from app.core.ownership import layer_of

BACKEND = Path(__file__).resolve().parents[1]
MODULES_ROOT = BACKEND / "app" / "modules"
SETTINGS_REGISTRY = MODULES_ROOT / "settings" / "registry.py"
APP_JSX = BACKEND.parent / "frontend" / "src" / "App.jsx"


def _settings_registry_domains() -> set[str]:
    """The domains the settings registry actually files keys under.

    Read from the source rather than by importing the module: the registry
    imports the whole settings stack, and this test is about names, not about
    standing a service up.
    """
    source = SETTINGS_REGISTRY.read_text(encoding="utf-8")
    start = source.index("_DOMAIN_HOME")
    block = source[start : source.index("}", start)]
    return set(re.findall(r'"([a-z_]+)":\s*\(', block))


def test_manifest_identifies_one_sector_application() -> None:
    assert APP_MANIFEST.key == "apparel"
    assert APP_MANIFEST.industry == "apparel"
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_MANIFEST.version)
    assert APP_MANIFEST.entrypoint.startswith(PREFIX)
    assert APP_MANIFEST.modules == MODULES


def test_module_keys_are_unique_and_present() -> None:
    keys = module_keys()
    assert keys, "an application with no modules has no reason to exist"
    assert len(set(keys)) == len(keys), f"duplicate module keys: {keys}"


def test_every_module_names_backend_packages_that_exist() -> None:
    missing: list[str] = []
    for module in MODULES:
        assert module.backend_modules, f"{module.key} names no backend package"
        for package in module.backend_modules:
            if not (MODULES_ROOT / package / "__init__.py").exists():
                missing.append(f"{module.key} -> app.modules.{package}")
            elif layer_of(package) != "apparel":
                missing.append(
                    f"{module.key} -> app.modules.{package} is classified {layer_of(package)}"
                )
    assert missing == [], f"modules claim packages that do not exist as apparel code: {missing}"


def test_every_module_has_a_permission_and_a_screen() -> None:
    bare: list[str] = []
    for module in MODULES:
        if not codes_for_module(module.key):
            bare.append(f"{module.key}: no permission")
        if not routes_for_module(module.key):
            bare.append(f"{module.key}: no screen")
    assert bare == [], f"a module must be reachable and permitted: {bare}"


def test_permissions_are_namespaced_owned_and_unique() -> None:
    codes = [permission.code for permission in PERMISSIONS]
    assert len(set(codes)) == len(codes), "duplicate permission codes"
    area_owner: dict[str, str] = {}
    for permission in PERMISSIONS:
        assert permission.code.startswith(NAMESPACE), permission.code
        assert permission.module in module_keys(), permission.code
        parts = permission.code.split(".")
        assert len(parts) == 3, f"{permission.code} must be apparel.<area>.<action>"
        area = parts[1]
        # One public area, one owning module: two modules answering to the
        # same permission code is how an access check ends up unowned.
        assert area_owner.setdefault(area, permission.module) == permission.module, (
            f"area {area} is claimed by both {area_owner[area]} and {permission.module}"
        )
        assert permission.title_ar and permission.title_en, permission.code


def test_routes_are_prefixed_unique_and_owned() -> None:
    paths = [route.path for route in ROUTES]
    assert len(set(paths)) == len(paths), f"duplicate routes: {paths}"
    for route in ROUTES:
        assert route.path.startswith(f"{PREFIX}/"), route.path
        assert route.module in module_keys() or route.module == SHELL, route.path


def test_legacy_routes_still_exist_in_the_frontend() -> None:
    """A compatibility path that no longer exists is a broken promise."""
    app_source = APP_JSX.read_text(encoding="utf-8")
    missing = [path for path in legacy_paths() if f'path="{path}"' not in app_source]
    assert missing == [], f"legacy paths declared but absent from App.jsx: {missing}"


def test_events_are_unique_across_modules() -> None:
    events = [event for module in MODULES for event in module.events]
    assert len(set(events)) == len(events), f"duplicate event names: {events}"


def test_settings_ownership_covers_the_registry_and_does_not_overlap() -> None:
    platform = PLATFORM_SETTINGS_DOMAINS
    apparel = owned_settings_domains()
    assert platform & apparel == set(), f"claimed by both layers: {sorted(platform & apparel)}"

    in_registry = _settings_registry_domains()
    unclaimed = sorted(domain for domain in in_registry if owner_of(domain) is None)
    assert unclaimed == [], (
        "every settings domain in the registry must belong to the platform or to "
        f"an application; unclaimed: {unclaimed}"
    )


def test_platform_domains_are_not_claimed_by_the_application() -> None:
    for domain in PLATFORM_SETTINGS_DOMAINS:
        assert owner_of(domain) == "platform", domain
