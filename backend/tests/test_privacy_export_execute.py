"""An export request must be completable, not just creatable.

Without the access/export branch in the execute route, those two request types
could be created and never finished: the row stayed pending forever and
``result_ref`` (the column the schema reserves for the produced export) was
never written.
"""

from __future__ import annotations

import pathlib

ROUTER = pathlib.Path(__file__).resolve().parents[1] / "app/modules/privacy/router.py"
SERVICE = pathlib.Path(__file__).resolve().parents[1] / "app/modules/privacy/service.py"


def test_execute_accepts_access_and_export() -> None:
    source = ROUTER.read_text()
    assert '"delete", "access", "export"' in source
    # The old guard refused everything except delete.
    assert 'if request.request_type != "delete":\n        raise ValidationError' not in source


def test_execute_export_writes_the_result_reference() -> None:
    source = SERVICE.read_text()
    assert "async def execute_export" in source
    assert 'request.result_ref = f"inline:{digest}"' in source
    assert 'request.status = "completed"' in source


def test_export_payload_covers_the_customers_own_data() -> None:
    source = SERVICE.read_text()
    for section in ('"customer": plain(customer)', '"consents"', '"orders"', '"data_requests"'):
        assert section in source
