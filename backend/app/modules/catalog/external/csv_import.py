"""Spec §161 — CSV import pipeline.

Never injects directly into the DB. The pipeline is:
    Import → Validation → Identity Resolution → Deduplication →
    Domain Application Services (CustomerService, ProductService, etc.)

This ensures the same business rules, audit, and events apply whether a
record comes from a CSV, an API call, or an external sync.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportRow:
    """One row from the CSV, validated and ready for the service layer."""
    row_number: int
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportReport:
    """Summary of an import operation."""
    total_rows: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[dict] = field(default_factory=list)


class CSVImportService:
    """§161: CSV import through Application Services, never direct DB.

    Supports customer and product imports. Each row is validated, passed
    through identity resolution (for customers) or deduplication (for
    products), and then handed to the relevant service.
    """

    REQUIRED_CUSTOMER_FIELDS = {"name"}
    OPTIONAL_CUSTOMER_FIELDS = {"email", "phone", "source", "tags"}

    REQUIRED_PRODUCT_FIELDS = {"title"}
    OPTIONAL_PRODUCT_FIELDS = {"slug", "description", "price", "sku", "status"}

    @staticmethod
    def parse_csv(raw: str | bytes) -> list[dict[str, str]]:
        """Parse CSV content into a list of dict rows."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        return list(reader)

    @staticmethod
    async def import_customers(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        raw_csv: str | bytes,
        customer_service,
    ) -> ImportReport:
        """Import customers from CSV via CustomerService.

        Identity resolution: if a customer with the same phone or email
        already exists, the row is skipped (not duplicated). The service
        layer makes the final decision, not this pipeline.
        """
        rows = CSVImportService.parse_csv(raw_csv)
        report = ImportReport(total_rows=len(rows))

        for i, row in enumerate(rows, start=1):
            import_row = ImportRow(row_number=i, data=row)

            # Validate required fields
            if not row.get("name"):
                import_row.errors.append("name is required")

            if import_row.errors:
                report.errors += 1
                report.error_details.append({
                    "row": i,
                    "errors": import_row.errors,
                })
                continue

            try:
                await customer_service.create_from_import(
                    session,
                    tenant_id,
                    name=row["name"].strip(),
                    email=row.get("email", "").strip() or None,
                    phone=row.get("phone", "").strip() or None,
                    source=row.get("source", "csv_import").strip(),
                    tags=row.get("tags", "").strip() or None,
                )
                report.imported += 1
            except Exception as exc:
                logger.warning("csv customer import row %d: %s", i, exc)
                report.errors += 1
                report.error_details.append({
                    "row": i,
                    "errors": [str(exc)],
                })

        return report

    @staticmethod
    async def import_products(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        raw_csv: str | bytes,
        product_service,
    ) -> ImportReport:
        """Import products from CSV via ProductService."""
        rows = CSVImportService.parse_csv(raw_csv)
        report = ImportReport(total_rows=len(rows))

        for i, row in enumerate(rows, start=1):
            if not row.get("title"):
                report.errors += 1
                report.error_details.append({
                    "row": i,
                    "errors": ["title is required"],
                })
                continue

            try:
                await product_service.create(
                    session,
                    tenant_id,
                    title=row["title"].strip(),
                    slug=row.get("slug", "").strip() or None,
                    description=row.get("description", "").strip() or None,
                )
                report.imported += 1
            except Exception as exc:
                logger.warning("csv product import row %d: %s", i, exc)
                report.errors += 1
                report.error_details.append({
                    "row": i,
                    "errors": [str(exc)],
                })

        return report
