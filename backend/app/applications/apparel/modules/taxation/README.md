# taxation

TAXATION domain: the legal identity of the business and the tax class of what it sells.

By default a shelf price INCLUDES tax and the tax is extracted from it, so the total a customer
pays never changes because a shop turned VAT on. Each line's tax is rounded to the piaster on its
own and the document tax is the sum of the rounded lines (that is what the tax authority
reconciles).

## Where things are

- `calc.py` (pure, exact Decimal arithmetic, no database)
- `models.py`
- `router.py`
- `service.py`

## HTTP

Route prefixes: see `router.py`. Registered in `app/main.py`.

## Tables

- `business_profiles`
- `tax_classes`
