"""Write what the messages API returns for sample customer carts, for the frontend tests.

The screen must draw exactly what the server sends, so its tests read THIS output instead of a
shape typed by hand. Re-run after changing gateway/whatsapp_order.py:

    python scripts/export_order_fixtures.py
"""

import json
from pathlib import Path

from app.applications.apparel.modules.conversations.gateway.whatsapp_order import parse_order

OUT = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/components/inbox/whatsapp/__fixtures__/order_server.json"
)


def _msg(**order):
    return {"type": "order", "order": order}


def _line(rid, qty, price=9.5):
    return {"product_retailer_id": rid, "quantity": qty, "item_price": price, "currency": "EGP"}


RAW = {
    "two_lines_with_note": _msg(
        catalog_id="c1",
        text="بسرعة لو سمحت",
        product_items=[_line("SKU-RED-M", 2), _line("حذاء-42", 1)],
    ),
    "one_line": _msg(catalog_id="c1", product_items=[_line("SKU-1", 1)]),
    "one_unreadable": _msg(catalog_id="c1", product_items=[_line("SKU-1", 3), {"quantity": 0}]),
    "long_id": _msg(catalog_id="c1", product_items=[_line("X" * 150, 1)]),
}

if __name__ == "__main__":
    data = {name: parse_order(raw) for name, raw in RAW.items()}
    OUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT} ({len(data)} carts)")
