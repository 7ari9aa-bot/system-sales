"""Two first writes of the same setting: one creates, the other must see it.

``set()`` had no row to lock when a setting had never been written, and the insert used
ON CONFLICT DO UPDATE. So the loser silently overwrote the winner AND recorded
``old_value = None`` in history — the audit trail claimed nothing was replaced while a
value was replaced, and an optimistic expectation could not fail because there was no
revision to compare against.
"""

from __future__ import annotations

import inspect
import pathlib

from app.modules.settings.service import SettingsService

SOURCE = pathlib.Path(inspect.getfile(SettingsService)).read_text(encoding="utf-8")
START = SOURCE.index("async def set(")
REST = SOURCE[START + 10 :]
SET_BODY = SOURCE[START : START + 10 + REST.index("\n    async def ")]


def test_the_insert_does_not_overwrite_a_concurrent_creator() -> None:
    assert "on_conflict_do_nothing" in SET_BODY
    assert "on_conflict_do_update" not in SET_BODY, (
        "DO UPDATE lets the loser overwrite the winner and lose the real old value"
    )


def test_the_loser_takes_the_locked_update_path() -> None:
    assert "if insert_id is None:" in SET_BODY
    after = SET_BODY.split("if insert_id is None:")[1]
    assert "for_update=True" in after
    assert "old_value = winner.value" in after


def test_the_loser_still_honours_an_optimistic_expectation() -> None:
    after = SET_BODY.split("if insert_id is None:")[1]
    assert "expected_history_id is not None" in after
    assert "ConflictError" in after


def test_the_creator_records_no_old_value() -> None:
    after = SET_BODY.split("else:", 1)[1]
    assert "old_value = None" in after


def test_a_vanished_row_is_a_conflict_not_a_crash() -> None:
    assert "disappeared while writing" in SET_BODY
