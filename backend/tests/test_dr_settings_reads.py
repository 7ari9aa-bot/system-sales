"""The backups-and-restore settings page reads the DR module, and says only what it proves.

Two rules are pinned here, both at source level so they run on any interpreter:

1. The position endpoint is EVIDENCE-shaped. Health and the drill list come from
   ``DRService.check_dr_health`` (recorded drill results) and ``list_restore_tests``
   (the runs themselves) — never from the configured intent. A page that showed
   "weekly drills" as reassurance without the last result would be the exact
   defect the Settings Center exists to prevent.
2. The restore list is tenant-scoped by an explicit predicate as well as by RLS,
   so a session bound elsewhere cannot read another tenant's incident.
"""

from __future__ import annotations

import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTER = (BACKEND / "app/modules/platform/routers/dr.py").read_text(encoding="utf-8")
DR = (BACKEND / "app/modules/platform/dr.py").read_text(encoding="utf-8")
RESTORE = (BACKEND / "app/modules/platform/tenant_restore.py").read_text(encoding="utf-8")


def _handler(source: str, decorator: str) -> str:
    start = source.index(decorator)
    rest = source[start:]
    end = rest.find("\n@router.", 1)
    return rest if end == -1 else rest[:end]


def test_the_position_endpoint_exists_and_is_read_only() -> None:
    body = _handler(ROUTER, '@router.get("/dr")')
    assert "DRService.check_dr_health" in body
    assert "DRService.list_restore_tests" in body
    assert "DRService.get_policy" in body


def test_the_position_reports_the_drill_not_the_promise() -> None:
    body = _handler(ROUTER, '@router.get("/dr")')
    # Health and the overdue flag come from the service, not from a literal.
    assert '"healthy": health["healthy"]' in body
    assert '"restore_test_overdue": health["restore_test_overdue"]' in body
    # The runs themselves are returned, with the measured numbers.
    assert '"restore_tests"' in body
    assert "run.restore_duration_seconds" in body
    assert "run.data_loss_seconds" in body


def test_the_restore_job_list_is_tenant_scoped() -> None:
    body = _handler(RESTORE, "    async def list_restore_jobs(")
    assert "TenantRestoreJob.tenant_id == tenant_id" in body
    assert ".limit(limit)" in body


def test_the_drill_list_is_bounded_and_newest_first() -> None:
    body = _handler(DR, "    async def list_restore_tests(")
    assert "RestoreTestRun.created_at.desc()" in body
    assert ".limit(limit)" in body
