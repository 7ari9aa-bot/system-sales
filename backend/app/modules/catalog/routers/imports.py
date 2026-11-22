"""CSV import endpoints for the catalog module (§161).

The products door here is the OLD one: one CSV row became one product with a single default
variant, under rules of its own. The Import Center replaced it (many sheets, many variants, one
opening stock per SKU, the same fields as the add-product screen), so the door is closed for the
merchant behind ``imports.legacy_csv_endpoint`` — a data key, not a deletion. Even when the key is
on, a file that arrives here is turned into an ordinary import session and checked by the same
validation as any other upload: there is one pipeline, and this is only a different way in.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.errors import NotFoundError
from app.modules.catalog.external.csv_import import CSVImportService
from app.modules.imports import service as import_service
from app.modules.settings.service import SettingsService

from ._deps import (
    CsvImportRequest,
    CustomerWriteCtx,
    WriteCtx,
    _audit_import,
    _report_out,
    _report_status,
)

router = APIRouter()


@router.post("/imports/customers")
async def import_customers_csv(ctx: CustomerWriteCtx, body: CsvImportRequest):
    """§161: import customers from a CSV through CustomerService, never the DB."""
    from app.modules.customers.service import CustomerService

    report = await CSVImportService.import_customers(
        ctx.session,
        ctx.tenant_id,
        raw_csv=body.csv,
        customer_service=CustomerService,
    )
    await _audit_import(ctx, "customer.csv_import", "customer", report)
    return JSONResponse(status_code=_report_status(report), content=_report_out(report))


@router.post("/imports/products")
async def import_products_csv(ctx: WriteCtx, body: CsvImportRequest):
    """The old single-sheet CSV door: closed unless the shop's data key opens it.

    Closed, it answers 404 like a route that no longer exists and points at the Import Center.
    Open, the file is NOT applied here: it becomes an ordinary import session and goes through
    ``validate_session`` exactly like a workbook dropped in the Import Center, so a row that
    would be refused there is refused here too.
    """
    enabled = await SettingsService(ctx.session, ctx.tenant_id).value("imports.legacy_csv_endpoint")
    if not enabled:
        raise NotFoundError(
            "استيراد المنتجات بقى من مركز الاستيراد (ملف Excel أو CSV): /inventory/import"
        )

    imp = await import_service.create_session(
        ctx.session,
        ctx.tenant_id,
        file_name="products.csv",
        data=body.csv.encode("utf-8"),
        user_id=ctx.user.id,
    )
    imp = await import_service.validate_session(ctx.session, ctx.tenant_id, imp.id)
    from app.core.audit import write_audit_row

    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        action="catalog.csv_import",
        resource_type="import_session",
        resource_id=str(imp.id),
        after={"file_name": imp.file_name, "status": imp.status, "stats": imp.stats},
    )
    return JSONResponse(
        status_code=200,
        content={
            "session_id": str(imp.id),
            "status": imp.status,
            "stats": imp.stats,
            "import_center": "/inventory/import",
        },
    )
