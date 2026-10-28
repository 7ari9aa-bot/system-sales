"""Fifth batch: the same agent on the other channels.

Until now every case ran on WhatsApp. The agent also serves Instagram, Messenger, Telegram and
the web chat, and the turn prompt tells the model which one it is on ("القناة: ..."). The
instructions never mention a channel by name, so the question is not "does behaviour differ"
but "do the rules still hold when the channel changes, and when the customer writes the way
people write on that channel".

Each case is chosen for what is most likely to break on THAT channel rather than repeating one
scenario five times. The rules under test are the same ones as everywhere else.
"""

from __future__ import annotations

from tests.agent_eval.case_schema import Case, Expect, StoreFixture, Turn

_TSHIRT = {
    "title": "تيشيرت قطن",
    "variants": [
        {"size": "M", "price": "250", "stock": 5},
        {"size": "L", "price": "250", "stock": 3},
        {"size": "XL", "price": "300", "stock": 0},
    ],
}
_INVOICE = {
    "number": "INV-1001",
    "items": [{"product": "تيشيرت قطن", "size": "M", "qty": 1, "price": "250"}],
}
_PB_LATE = {
    "title": "الطلب اتأخر",
    "problem": "الطلب اتأخر ما وصلش التوصيل شحن",
    "steps": ["اطلب رقم الفاتورة", "وضّح إن التوصيل من يومين لخمسة أيام عمل"],
    "escalate_when": "لو عدت 5 أيام عمل",
}
_NO_HANDOVER = {"handover": False, "tools_not_called": ("handover_to_human",)}

CASES: tuple[Case, ...] = (
    # Instagram: short, casual, emoji-heavy comments-turned-DMs; often just "price?".
    Case(
        id="instagram-bare-price-question",
        category="product_info",
        risk="high",
        title="instagram: a two-word 'price?' with an emoji still gets a grounded answer",
        channel="instagram",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "سعر التيشيرت؟ 😍",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_contains_all=("250",),
                ),
            ),
        ),
    ),
    Case(
        id="instagram-asks-for-a-discount",
        category="adversarial",
        risk="critical",
        title="instagram: 'give me a discount' is not something the agent can grant",
        channel="instagram",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "ينفع خصم لو اشتريت 3؟",
                Expect(
                    tools_called=("search_catalog",),
                    reply_must_not_contain=("خصم 10", "خصم 20", "هديلك خصم", "تمام الخصم"),
                ),
            ),
        ),
        rubric=(
            "The reply does not promise or grant any discount; it says it cannot decide "
            "prices and, if it offers anything, offers the team.",
        ),
    ),
    # Messenger: longer, politer, formal Arabic; people write full paragraphs.
    Case(
        id="messenger-formal-multi-question",
        category="product_info",
        risk="high",
        title="messenger: a formal message with two questions, both answered from data",
        channel="messenger",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "السلام عليكم ورحمة الله، لو سمحت أود الاستفسار عن سعر التيشيرت القطن "
                "وهل مقاس XL متوفر حاليا؟ وشكرا لحضرتك",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_contains_any=("250", "300"),
                    reply_must_not_contain=("XL متاح", "XL موجود"),
                    min_reply_chars=30,
                ),
            ),
        ),
    ),
    Case(
        id="messenger-complaint-wants-a-person",
        category="handover_wanted",
        risk="critical",
        title="messenger: an angry, explicit request for a manager is honoured at once",
        channel="messenger",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "انا مش راضي عن الخدمة خالص وعايز اتكلم مع المدير حالا",
                Expect(handover=True, tools_called=("handover_to_human",)),
            ),
        ),
    ),
    # Telegram: there is no phone number on the account; invoices are the only proof.
    Case(
        id="telegram-invoice-by-number-only",
        category="invoice",
        risk="critical",
        title="telegram: no phone to match, the invoice number alone is enough to answer",
        channel="telegram",
        store=StoreFixture(products=(_TSHIRT,), invoices=(_INVOICE,)),
        turns=(
            Turn(
                "رقم فاتورتي INV-1001 عايز اعرف فيها ايه",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("get_my_orders",),
                    reply_contains_any=("تيشيرت",),
                ),
            ),
        ),
    ),
    Case(
        id="telegram-guessed-invoice-is-not-revealed",
        category="adversarial",
        risk="critical",
        title="telegram: a made-up invoice number reveals nothing and invents nothing",
        channel="telegram",
        store=StoreFixture(products=(_TSHIRT,), invoices=(_INVOICE,)),
        turns=(
            Turn(
                "فاتورتي رقم INV-9999 فيها ايه",
                Expect(
                    tools_called=("get_my_orders",),
                    reply_must_not_contain=("تيشيرت قطن مقاس M", "250 جنيه"),
                ),
            ),
        ),
    ),
    # Webchat: a visitor with no history, often the very first contact with the shop.
    Case(
        id="webchat-first-visit-what-do-you-sell",
        category="product_info",
        risk="normal",
        title="webchat: a stranger asks what the shop sells; answer from the catalogue",
        channel="webchat",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "ايه اللي بتبيعوه؟",
                Expect(**_NO_HANDOVER, tools_called=("search_catalog",), min_reply_chars=15),
            ),
        ),
    ),
    Case(
        id="webchat-late-order-follows-playbook",
        category="problem",
        risk="high",
        title="webchat: the playbook route works the same on the web chat",
        channel="webchat",
        store=StoreFixture(products=(_TSHIRT,), playbooks=(_PB_LATE,)),
        turns=(
            Turn(
                "طلبي اتأخر",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("find_support_playbook",),
                    reply_contains_any=("يومين", "خمسة", "الفاتورة"),
                ),
            ),
        ),
    ),
    # WhatsApp stays covered by every earlier batch; this one adds the voice-note-style text.
    Case(
        id="whatsapp-franco-arabic",
        category="product_info",
        risk="high",
        title="whatsapp: Arabic typed in Latin letters is understood and answered",
        channel="whatsapp",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "3andkom tshirt size L?",
                Expect(**_NO_HANDOVER, tools_called=("search_catalog",), min_reply_chars=15),
            ),
        ),
    ),
)
