# einvoice

E-invoicing and fiscal compliance module (ZATCA Saudi Arabia, ETA Egypt, Peppol UAE).

## Where things are

- `models.py` — Devices, CSID certificates, counters, electronic invoice documents, and hash chains.
- `ports.py` — `EInvoiceProvider` abstract base interface and domain DTOs.
- `registry.py` — Provider factory matching tenant country to compliance engine.
- `service.py` — Orchestrator for document generation, digital signing, and clearance/reporting.
- `providers/` — Provider implementations (ZATCA, ETA, Peppol, Sandbox).

## Tables

- `einvoice_devices` (tenant-scoped)
- `einvoice_documents` (tenant-scoped)

## Rules for working here

- Business rules live in the service and provider layers.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Invoices, cryptographic hashes, and sequential counters (ICV, PIH) are append-only.
