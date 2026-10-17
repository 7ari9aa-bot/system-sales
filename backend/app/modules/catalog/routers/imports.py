"""CSV import endpoints for the catalog module (§161)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.modules.catalog.external.csv_import import CSVImportService

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
    """§161: import products from a CSV through the catalog's external upsert."""
    report = await CSVImportService.import_products(
        ctx.session,
        ctx.tenant_id,
        raw_csv=body.csv,
    )
    await _audit_import(ctx, "catalog.csv_import", "product", report)
    return JSONResponse(status_code=_report_status(report), content=_report_out(report))
