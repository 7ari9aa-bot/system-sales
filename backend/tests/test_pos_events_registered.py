"""§189 static guard — every event type the POS module stages is registered.

An unregistered event type makes ``build_envelope`` raise AT STAGING TIME,
inside the caller's transaction (core/events/writer.py builds the envelope
when the outbox row is written) — so one forgotten string silently kills the
whole business operation that tried to publish it. This guard parses the POS
service statically and refuses any ``event_type="..."`` literal that is not in
``DOMAIN_EVENT_TYPES``. DB-free; runs everywhere.
"""

from __future__ import annotations

import ast
import pathlib

from app.core.events.schemas import DOMAIN_EVENT_TYPES

POS_SERVICE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "app"
    / "modules"
    / "pos"
    / "service.py"
)


def _staged_event_types(source: str) -> set[str]:
    """Every literal passed as ``event_type=`` anywhere in the module."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword):
            continue
        if node.arg != "event_type":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            found.add(node.value.value)
    return found


def test_every_pos_event_type_is_registered() -> None:
    source = POS_SERVICE.read_text(encoding="utf-8")
    staged = _staged_event_types(source)
    assert staged, "the guard found no staged events — did the module move?"
    unregistered = sorted(staged - set(DOMAIN_EVENT_TYPES))
    assert unregistered == [], (
        "POS stages event type(s) missing from DOMAIN_EVENT_TYPES — build_envelope "
        f"would raise inside the caller's transaction: {unregistered}"
    )
