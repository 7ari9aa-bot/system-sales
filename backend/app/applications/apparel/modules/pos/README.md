# pos

POS domain — the point-of-sale adapter (Commerce Core v1.0 §189).

## Where things are

- `models.py`
- `override.py`
- `profiles.py`
- `receipt_reads.py` (read-only receipt queries; `PosService` inherits them)
- `router.py`
- `service.py` (the rules; the largest file in the repo, split further only along seams that do not touch `datetime`, see below)
- `stock_view.py`

## HTTP

42 endpoints. Route prefixes: `/pos`. Registered in `app/main.py`.

## Tables

- `pos_cash_movements`
- `pos_daily_sales`
- `pos_held_carts`
- `pos_profile_users`
- `pos_profiles`
- `pos_receipts`
- `pos_registers`
- `pos_return_lines`
- `pos_session_floats`
- `pos_session_handovers`
- `pos_session_reconciliations`
- `pos_sessions`

## Depends on

Other modules imported from here: `analytics`, `catalog`, `customers`, `identity`, `inventory`, `orders`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Splitting `service.py` safely

`service.py` is still large. Two things make splitting it risky, so check them first:

1. **Tests freeze the clock by patching `app.modules.pos.service.datetime`.** A method that uses
   `datetime` must stay in `service.py`, or the patch silently stops applying to it and the
   test runs on the real clock. These use it today: `_ensure_session_current`, `_issue_receipt`,
   `_record_close`, `top_products`, `sales_by_day`.
2. **Methods call each other as `PosService._name(...)`, not `self.`.** Measure dependencies by
   that spelling. The return and exchange methods depend on 11 other methods, including two that
   use `datetime`, so they cannot move cleanly yet.

`receipt_reads.py` was split out because its four methods call no other `PosService` method and
never touch `datetime`. Prove any further move with an AST comparison and the full POS suite.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `pos` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
