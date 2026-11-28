"""The boundary between the platform layer and a sector application.

The platform runs accounts, licences and operations. An application owns a
sector's rules and data. An application may use the platform; the platform may
never use an application, because that is how "the platform" quietly becomes a
business core that every sector has to fit into.

The test reads the source instead of trusting the folder layout, and it fails
on an unclassified module: a module nobody placed would otherwise be exempt
from every rule here.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.ownership import APPAREL_MODULES, PLATFORM_MODULES, layer_of

MODULES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules"

#: Platform modules that still reach into an application, one entry per
#: (source file, application module) pair. This is debt, not permission: the
#: list may only shrink, and an entry that no longer exists fails the test so it
#: is removed the same day it is paid off. Each entry is a place where the
#: platform reads sector data directly instead of through a declared contract.
KNOWN_PLATFORM_TO_APPAREL_LEAKS: frozenset[tuple[str, str]] = frozenset(
    {
        ("activity/router.py", "analytics"),
        ("imports/image_zip.py", "catalog"),
        ("imports/router.py", "catalog"),
        ("imports/validation.py", "catalog"),
        ("operations/slo_service.py", "ai"),
        ("privacy/service.py", "customers"),
        ("voice/application/assistant_turn.py", "ai"),
        ("voice/application/session_thread.py", "ai"),
        ("voice/application/transcript_sync.py", "ai"),
    }
)

_ABSOLUTE = re.compile(r"^\s*from\s+app\.modules\.([A-Za-z_]\w*)")
_ABSOLUTE_IMPORT = re.compile(r"^\s*import\s+app\.modules\.([A-Za-z_]\w*)")
_RELATIVE = re.compile(r"^\s*from\s+(\.{2,})([A-Za-z_]\w*)")


def _module_dirs() -> list[Path]:
    return sorted(p for p in MODULES_ROOT.iterdir() if p.is_dir() and (p / "__init__.py").exists())


def _known_modules() -> set[str]:
    return {d.name for d in _module_dirs()}


def _imports(path: Path) -> set[str]:
    """Every sibling module a file imports, absolute or relative.

    Read line by line rather than through ``ast``: the release targets Python
    3.12 and uses its syntax (PEP 695 generics), which a 3.11 interpreter in a
    developer sandbox cannot parse. A parser that dies on the first such file
    would report no imports at all, and a boundary test that sees nothing
    passes everything.
    """
    known = _known_modules()
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        for pattern in (_ABSOLUTE, _ABSOLUTE_IMPORT):
            match = pattern.match(line)
            if match:
                found.add(match.group(1))
        relative = _RELATIVE.match(line)
        if relative:
            found.add(relative.group(2))
    return found & known


def test_every_module_is_classified() -> None:
    unclassified = sorted(d.name for d in _module_dirs() if layer_of(d.name) is None)
    assert unclassified == [], (
        "every module under app/modules must be placed in app/core/ownership.py "
        f"as platform, apparel or shared; unclassified: {unclassified}"
    )


def test_ownership_maps_do_not_overlap() -> None:
    overlap = sorted(PLATFORM_MODULES & APPAREL_MODULES)
    assert overlap == [], f"a module cannot belong to both layers: {overlap}"


def test_platform_never_imports_an_application_module() -> None:
    violations: list[tuple[str, str]] = []
    for module_dir in _module_dirs():
        if layer_of(module_dir.name) != "platform":
            continue
        for path in sorted(module_dir.rglob("*.py")):
            relative = f"{module_dir.name}/{path.relative_to(module_dir).as_posix()}"
            for target in sorted(_imports(path)):
                if target not in APPAREL_MODULES:
                    continue
                if (relative, target) in KNOWN_PLATFORM_TO_APPAREL_LEAKS:
                    continue
                violations.append((relative, target))

    assert violations == [], (
        "the platform layer must not import a sector application's modules. "
        "Declare a contract or move the logic instead. New leaks: "
        f"{violations}"
    )


def test_known_leaks_are_still_real_so_the_list_can_only_shrink() -> None:
    present: set[tuple[str, str]] = set()
    for module_dir in _module_dirs():
        for path in sorted(module_dir.rglob("*.py")):
            relative = f"{module_dir.name}/{path.relative_to(module_dir).as_posix()}"
            for target in _imports(path):
                present.add((relative, target))

    stale = sorted(KNOWN_PLATFORM_TO_APPAREL_LEAKS - present)
    assert stale == [], (
        "these leaks are already gone, so remove them from "
        f"KNOWN_PLATFORM_TO_APPAREL_LEAKS: {stale}"
    )


def test_application_may_use_the_platform() -> None:
    """The allowed direction: an application depends on platform infrastructure."""
    reachable = any(
        target in PLATFORM_MODULES
        for module_dir in _module_dirs()
        if layer_of(module_dir.name) == "apparel"
        for path in module_dir.rglob("*.py")
        for target in _imports(path)
    )
    assert reachable, (
        "no application module uses the platform at all, which suggests the "
        "import scanner is broken and would hide real leaks"
    )
