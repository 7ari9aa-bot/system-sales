"""Spec §161 — CSV import pipeline.

Never injects directly into the DB. The pipeline is:
    Import → Validation → Identity Resolution → Deduplication →
    Domain Application Services (CustomerService, CatalogService, etc.)

This ensures the same business rules, audit, and events apply whether a
record comes from a CSV, an API call, or an external sync. Products go
through the same ``CatalogService.upsert_from_external`` the Shopify adapter
uses — a re-uploaded CSV updates the row it already owns, never a clone.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import storage_refusal
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError

logger = logging.getLogger(__name__)

_CHANNEL = "csv"


@dataclass(slots=True)
class ImportRow:
    """One row from the CSV, validated and ready for the service layer."""
    row_number: int
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportReport:
    """Summary of an import operation.

    ``success`` is the verdict callers must read: a row that failed or was
    refused by a domain rule keeps the run non-green, whatever the counters
    otherwise look like.
    """
    total_rows: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    conflicts: int = 0
    error_details: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.errors == 0 and self.conflicts == 0


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _row_ref(row: dict[str, str], title: str) -> str:
    """The stable key a re-upload recognises: slug, ASCII title, title hash.

    Arabic-only titles slugify to nothing; hashing the raw title keeps the
    identity stable across re-uploads without inventing a random one.
    """
    slug = (row.get("slug") or "").strip()
    if slug:
        return slug
    return _slugify(title) or f"{_CHANNEL}-{hashlib.sha1(title.encode()).hexdigest()[:12]}"


class CSVImportService:
    """§161: CSV import through Application Services, never direct DB.

    Supports customer and product imports. Each row is validated, passed
    through identity resolution (for customers) or deduplication (for
    products), and then handed to the relevant service.
    """

    REQUIRED_CUSTOMER_FIELDS = {"name"}
    OPTIONAL_CUSTOMER_FIELDS = {"email", "phone", "source", "tags"}

    REQUIRED_PRODUCT_FIELDS = {"title"}
    OPTIONAL_PRODUCT_FIELDS = {"slug", "description", "price", "sku", "status", "currency"}

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
        already exists, the row is refused as a conflict (never duplicated).
        The service layer makes the final decision, not this pipeline — each
        row is handed to ``CustomerService.create_from_import`` UNCHANGED, so
        the canonicalisation and duplicate rules a human write obeys apply
        here too.

        Refuses loudly before the first row if the owning service has no CSV
        intake. ``create_from_import`` is now defined on the real
        ``CustomerService``, so the production path never trips this; the guard
        only fires for a caller that hands in something without it, where a
        ``NotImplementedError`` beats an ``AttributeError`` swallowed into a
        report nobody reads (the defect class the Shopify sync shipped with).
        """
        if not hasattr(customer_service, "create_from_import"):
            raise NotImplementedError(
                "CSV customer import needs a service that owns the intake: "
                "CustomerService.create_from_import is the method that applies "
                "the customers identity rules; a caller that passes something "
                "without it cannot import. The production CustomerService "
                "defines it; this guard is for a wrong injected service only."
            )

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
            except ConflictError as exc:
                # A domain refusal is visible as a conflict, never a silent
                # entry next to a green report.
                report.conflicts += 1
                logger.warning("csv customer import conflict row %d: %s", i, exc)
                report.error_details.append({"row": i, "errors": [str(exc)]})
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
        product_service=None,
    ) -> ImportReport:
        """Import products from CSV via the catalog's external upsert.

        One intake path for every external source (§161): the CSV row is
        normalized to the canonical shape and handed to
        ``CatalogService.upsert_from_external``, which owns the slug/row
        identity, the provenance stamp, and the §47 currency gate.
        """
        service = product_service if product_service is not None else CatalogService
        rows = CSVImportService.parse_csv(raw_csv)
        report = ImportReport(total_rows=len(rows))

        for i, row in enumerate(rows, start=1):
            title = (row.get("title") or "").strip()
            if not title:
                report.errors += 1
                report.error_details.append({
                    "row": i,
                    "errors": ["title is required"],
                })
                continue

            slug = _row_ref(row, title)
            price = (row.get("price") or "").strip()
            sku = (row.get("sku") or "").strip()
            declared = (row.get("currency") or "").strip().upper() or None

            # A code the schema cannot hold is refused before the row is
            # normalized: three decimals into NUMERIC(14,2) loses a minor
            # unit on every price (§47). A foreign-but-storable code is
            # refused by the service itself, against the tenant's own row.
            if declared:
                refusal = storage_refusal(declared)
                if refusal:
                    report.conflicts += 1
                    message = f"{_CHANNEL} import row {i} refused: {refusal}"
                    logger.warning("%s", message)
                    report.error_details.append({"row": i, "errors": [message]})
                    continue

            data: dict[str, Any] = {
                "title": title,
                "slug": slug,
                "description": (row.get("description") or "").strip() or None,
                "status": (row.get("status") or "").strip() or None,
            }
            if price or sku:
                data["variants"] = [
                    {"title": "Default", "price": price or None, "sku": sku or None}
                ]

            try:
                await service.upsert_from_external(
                    session,
                    tenant_id,
                    external_ref=slug,
                    data=data,
                    source=_CHANNEL,
                    currency=declared,
                )
                report.imported += 1
            except ConflictError as exc:
                report.conflicts += 1
                logger.warning("csv product import conflict row %d: %s", i, exc)
                report.error_details.append({"row": i, "errors": [str(exc)]})
            except Exception as exc:
                logger.warning("csv product import row %d: %s", i, exc)
                report.errors += 1
                report.error_details.append({
                    "row": i,
                    "errors": [str(exc)],
                })

        return report
