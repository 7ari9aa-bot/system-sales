"""What the import screen reads, checked against the real routes and a real run.

The screen (frontend/src/cashier/api/importCenter.js) reads fixed keys from every answer. If one is
renamed or moved here, the screen breaks without any Python test failing: this file is that alarm.
"""

from __future__ import annotations

from sqlalchemy import select

from app.modules.inventory.models import Warehouse
from app.modules.platform.models import Job
from app.workers.import_runner import run_batch
from tests.test_imports_http import BOTH, XLSX, _xlsx, api  # noqa: F401, F811  (api is a fixture)

ARABIC = _xlsx(
    {
        "Products": [
            ["معرّف المنتج", "اسم المنتج", "التصنيف"],
            ["tee", "قميص قطن", "ملابس"],
            ["pants", "بنطلون جينز", "ملابس"],
            ["", "", "ملابس"],  # a name is required: this row is refused
        ],
        "Variants": [
            ["معرّف المنتج", "SKU", "السعر", "اللون", "المقاس"],
            ["tee", "TEE-R-M", "99.50", "أحمر", "M"],
            ["tee", "TEE-R-L", "99.50", "أحمر", "L"],
            ["pants", "PNT-B-32", "250", "أزرق", "32"],
        ],
    }
)


async def _flow(client, db, tenant_id):
    db.add(Warehouse(tenant_id=tenant_id, name="Main", code="MAIN"))
    up = await client.post(
        "/api/v1/imports/sessions",
        params={"filename": "كتالوج.xlsx"},
        content=ARABIC,
        headers={"content-type": XLSX},
    )
    assert up.status_code == 201, up.text
    return up.json()


async def test_upload_has_every_key_the_mapping_step_reads(api, db, tenant_ctx):  # noqa: F811
    async with api(BOTH) as client:
        s = await _flow(client, db, tenant_ctx.tenant_id)
    assert {"id", "status", "file_name", "options", "stats", "sheets"} <= s.keys()
    assert s["status"] == "analyzed"
    assert s["file_name"] == "كتالوج.xlsx"
    assert set(s["sheets"]) == {"Products", "Variants"}
    for sheet in s["sheets"].values():
        assert {"rows", "mapping", "missing_required", "fields"} <= sheet.keys()
        assert all({"key", "label_ar", "required"} <= f.keys() for f in sheet["fields"])
    # Arabic headers are recognised without the merchant touching anything.
    assert s["sheets"]["Products"]["mapping"]["اسم المنتج"] == "title"
    assert s["sheets"]["Products"]["missing_required"] == []
    assert s["sheets"]["Variants"]["mapping"]["اللون"] is not None
    assert s["stats"]["ignored_sheets"] == []


async def test_validate_then_preview_have_the_counters_the_review_step_reads(api, db, tenant_ctx):  # noqa: F811
    async with api(BOTH) as client:
        s = await _flow(client, db, tenant_ctx.tenant_id)
        base = f"/api/v1/imports/sessions/{s['id']}"
        mapped = await client.put(
            f"{base}/mapping",
            json={
                "mapping": {k: v["mapping"] for k, v in s["sheets"].items()},
                "options": {"duplicate_policy": "skip"},
            },
        )
        assert mapped.status_code == 200 and mapped.json()["status"] == "mapped"
        assert "sheets" in mapped.json()  # the mapping step re-renders from this answer

        v = (await client.post(f"{base}/validate")).json()
        assert v["status"] == "validated"
        assert "sheets" not in v  # the screen keeps the earlier `sheets` (cache merge)
        p = (await client.get(f"{base}/preview")).json()
    sheets = p["stats"]["sheets"]
    for name in ("Products", "Variants"):
        assert {"total", "valid", "invalid", "create", "update", "skip", "error_codes"} <= sheets[
            name
        ].keys()
    assert sheets["Products"]["invalid"] == 1 and sheets["Products"]["valid"] == 2
    assert sheets["Variants"]["valid"] == 3
    err = p["sample_errors"][0]
    assert {"sheet", "row", "errors"} <= err.keys()
    assert {"code", "field"} <= err["errors"][0].keys()


async def test_a_running_import_reports_the_counters_the_run_step_reads(api, db, tenant_ctx):  # noqa: F811
    async with api(BOTH) as client:
        s = await _flow(client, db, tenant_ctx.tenant_id)
        base = f"/api/v1/imports/sessions/{s['id']}"
        await client.put(
            f"{base}/mapping", json={"mapping": {k: v["mapping"] for k, v in s["sheets"].items()}}
        )
        await client.post(f"{base}/validate")
        started = (await client.post(f"{base}/start")).json()
        assert started["status"] == "running" and started["stats"]["to_apply"] == 5
        assert (
            "remaining" not in started["stats"]
        )  # before the first batch: the screen falls back to to_apply

        job = (await db.execute(select(Job).where(Job.id == started["job_id"]))).scalar_one()
        await run_batch(db, job, limit=2)
        mid = (await client.get(base)).json()
        assert mid["status"] == "running"
        assert (mid["stats"]["applied"], mid["stats"]["remaining"]) == (2, 3)

        nxt = (await db.execute(select(Job).where(Job.id == mid["job_id"]))).scalar_one()
        assert nxt.id != job.id
        await run_batch(db, nxt, limit=500)
        done = (await client.get(base)).json()
    assert done["status"] == "completed"
    assert (done["stats"]["applied"], done["stats"]["remaining"]) == (5, 0)
    assert done["stats"]["failed"] == 0
