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
- `verdicts.py`: stores a validator verdict on its row (`parsed`: action and clean values, money as
  strings) and reads it back, so the run applies what the preview showed, not a re-parse of `raw`.
- `apply.py`: applies one batch (at most 500 rows) of `valid` rows through `Ports`, sheet by sheet
  (products, variants, item codes, opening stock, images). Each row runs in its own savepoint: a refusal or a database
  error fails that row alone. It imports no other module; `app/workers/import_runner.py` supplies
  the real catalog and inventory calls.
- `mapping.py`: suggests which column is which field. A suggestion is shown, never applied
  silently.

## Tax item codes (EGS / GS1)

The `Item Codes` sheet (SKU, code type, code) registers the authority's item code on a variant as
a `product_identifiers` row of type `egs` / `gs1`, through `CatalogService.add_identifier`. What it
checks is only what can be known without the authority: a GS1 code must be a real GTIN (8, 12, 13
or 14 digits with the published check digit), an EGS code is kept exactly as written because its
format belongs to the authority. Whether a code is REGISTERED to this merchant needs their ETA
account and is not checked here. A code already on another variant is refused, never moved; one
variant carries one code per type; a re-run of the same file skips what is already there.

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
Also done: the `import.run` job handler (`app/workers/import_runner.py`). Still to come: the HTTP API and the screen (spec: Artifacts, "مركز استيراد البيانات").

## How a run works

The job runner commits only when a handler returns, so one handler looping over 100,000 rows would
be one transaction holding locks for the whole file and losing all of it on a crash. So each
`import.run` job applies at most 500 rows, then queues the next job for the same session (the job
points at its session through `correlation_id`; `jobs` has no payload column). A crash loses one
batch, the retry finds the same rows still `valid`, and a twin worker skips the locked rows
(`FOR UPDATE SKIP LOCKED`). Category and brand names, images and customers are not applied yet.
A stock row of 0 records nothing: the ledger refuses a movement of 0.
