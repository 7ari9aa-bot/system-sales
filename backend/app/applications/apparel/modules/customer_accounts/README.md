# customer_accounts

CUSTOMER ACCOUNTS domain: credit sales, instalment payments and deposits, kept as an
append-only ledger. The balance is the SUM of the entries and is never stored as a number to edit.

Sign convention (one place, never flipped): a positive balance is what the customer owes the
shop; a negative balance is credit the shop owes the customer (an unused deposit).

## Where things are

- `models.py`
- `router.py`
- `rules.py` (pure, exact, no database: the entry kinds and the balance arithmetic)
- `service.py`

## HTTP

Route prefixes: see `router.py`. Registered in `app/main.py`.

## Tables

- `customer_accounts`
- `customer_ledger`
