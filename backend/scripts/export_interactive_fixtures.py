"""Write the server's drawn form of sample interactive messages for the frontend tests.

The inbox shows a message at once from what the agent typed, then replaces it with what the server
returns. The two must be identical, so the frontend test compares them on THIS output. Re-run after
changing app/modules/conversations/gateway/whatsapp_interactive.py:

    python scripts/export_interactive_fixtures.py
"""

import json
from pathlib import Path

from app.applications.apparel.modules.conversations.gateway.whatsapp_interactive import build_interactive

OUT = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/components/inbox/whatsapp/__fixtures__/interactive_server.json"
)

SPECS = {
    "buttons_full": {
        "kind": "buttons",
        "header": {"type": "text", "text": "Order #7"},
        "body": "تأكيد الطلب؟",
        "footer": "شكرًا",
        "buttons": [{"id": "btn_1", "title": "تأكيد"}, {"id": "btn_2", "title": "إلغاء"}],
    },
    "buttons_minimal": {
        "kind": "buttons",
        "body": "Ok?",
        "buttons": [{"id": "btn_1", "title": "Yes"}],
    },
    "list_full": {
        "kind": "list",
        "header": {"type": "text", "text": "H"},
        "body": "اختر",
        "footer": "F",
        "button": "الخيارات",
        "sections": [
            {
                "title": "A",
                "rows": [
                    {"id": "row_1_1", "title": "سريع", "description": "يوم"},
                    {"id": "row_1_2", "title": "عادي"},
                ],
            },
            {"title": "B", "rows": [{"id": "row_2_1", "title": "x"}]},
        ],
    },
    "cta": {
        "kind": "cta_url",
        "body": "تابع",
        "label": "فتح",
        "url": "https://fihrist.world/o/1?a=1&b=2",
    },
    "cta_with_header": {
        "kind": "cta_url",
        "header": {"type": "text", "text": "H"},
        "body": "b",
        "footer": "f",
        "label": "L",
        "url": "http://x.example/a",
    },
}

if __name__ == "__main__":
    data = {name: {"spec": spec, "server": build_interactive(spec)} for name, spec in SPECS.items()}
    OUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT} ({len(data)} cases)")
