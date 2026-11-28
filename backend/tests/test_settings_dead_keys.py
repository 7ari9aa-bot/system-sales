"""No setting may be offered to the owner while nothing reads it.

The audit found keys the registry advertised and no code path ever read: the settings
screen showed a switch, the owner flipped it, and nothing happened. Wiring them (or
declaring one reserved) closed that, and this guard keeps it closed: a new key must
either appear in the code that reads it, or carry ``reserved=True`` and say so.
"""

from __future__ import annotations

import pathlib

from app.platform.settings.registry import REGISTRY

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


def _reader_blob() -> str:
    parts = []
    for path in APP_DIR.rglob("*.py"):
        if path.name == "registry.py":
            continue  # the definition is not a reader
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _is_read(key: str, blob: str) -> bool:
    """A key is read if its literal appears, or its whole family is generated and read.

    ``capability.*`` is one key per capability, generated from CAPABILITIES and read
    through ``f"capability.{name}"``, so no literal for a single key exists anywhere.
    """
    if key in blob:
        return True
    family = f"{key.split('.', 1)[0]}.{{"
    return family in blob


def test_every_registry_key_is_read_by_some_code_or_declared_reserved() -> None:
    blob = _reader_blob()
    unread = sorted(
        key for key, defn in REGISTRY.items() if not defn.reserved and not _is_read(key, blob)
    )
    assert unread == [], (
        "these settings are offered to the owner but nothing reads them: "
        f"{unread}. Wire a reader or set reserved=True with a reason."
    )


def test_the_registry_still_holds_every_key_it_advertised() -> None:
    """No key was dropped to make the guard pass."""
    assert len(REGISTRY) >= 119


def test_reserved_is_a_real_flag_the_definition_accepts() -> None:
    defn = next(iter(REGISTRY.values()))
    assert defn.reserved is False
    assert hasattr(defn, "reserved")
