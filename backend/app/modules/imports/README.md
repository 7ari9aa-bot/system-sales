# imports

IMPORTS domain: a merchant uploads a spreadsheet (Excel or CSV), maps its columns to Fihrist
fields, previews what would change, and a background job applies it in resumable batches.

## Where things are

- `models.py`: `import_sessions` (file, mapping, options, stats) and `import_rows` (every source
  row with its status and errors; `(session_id, sheet, row_number)` is the idempotency key).
- `fields.py`: the importable fields per sheet (Products, Variants, Opening Stock, Images) and
  the header spellings recognised for each, Arabic and English. One table feeds the matcher and
  the template, so they cannot drift.
- `reader.py`: reads xlsx/csv safely (size, row, column and zip-bomb limits; macros refused;
  formulas never evaluated; UTF-8 and Windows-Arabic CSV).
- `normalize.py`: turns a cell into a clean value or a precise error code (prices like
  `1.250,50` and `١٢٥٫٥`, Excel scientific-notation barcodes refused, invisible characters).
- `validation.py`: judges every row before anything is written, including duplicates inside the
  file and against what the shop already holds. Pure: the caller passes in `Existing`.
- `lookup.py`: reads what the shop already holds for the keys in the file (existing products,
  SKUs, barcodes, warehouses, opening stock already recorded), one query per kind of key in
  chunks of 500. Raw SQL on purpose: a read-model, so this module imports no other module's
  tables (`test_module_boundaries`). `tests/test_imports_lookup.py` runs it on a real database.
- `mapping.py`: suggests which column is which field. A suggestion is shown, never applied
  silently.

## Rules for working here

- The uploaded file is untrusted input. Limits are enforced while reading, not after.
- Identity of a product or variant is SKU, then barcode, then a stable external ref. A name
  alone never decides that two rows are the same thing.
- Opening stock goes through the inventory ledger (`InventoryService.move`, reason
  `opening_stock`, a service-only reason the API refuses), never by writing a balance. The ledger
  needs quantity > 0, so a stock row of 0 means "nothing to record", not a movement. A retried batch must not apply a row twice: skip rows already `applied`.
- A blank cell on update keeps the existing value. Clearing is an explicit option.
- Writes go through the catalog and inventory services, which own the rules, audit and events.
  Import them inside the function that needs them (lazy), so this module adds no module-scope
  coupling to `tests/test_module_boundaries.py`.
- Services `flush()` and never `commit()`; the caller owns the transaction.

## Status

Done: tables, reader, column matching, cell parsing, row validation and the database lookup.
Still to come: the `import.run` job handler, the HTTP API and the screen (spec: Artifacts, "مركز استيراد البيانات").
