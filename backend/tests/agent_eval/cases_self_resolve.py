"""Fourth batch: the agent must SOLVE things itself and hand over only when it truly cannot.

This is the standing rule for the customer agent: resolve inquiries, product questions,
policy and invoice questions with the tools it has; hand over for a genuinely unresolved
problem or an explicit request for a person. The first three batches leaned toward "does it
hand over when it must"; this one leans the other way, "does it refrain when it need not",
and covers the support playbook, the product-details tool and multi-turn conversations.
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
_JEANS = {
    "title": "جينز سليم",
    "variants": [
        {"size": "32", "price": "600", "stock": 4},
        {"size": "34", "price": "600", "stock": 0},
    ],
}
_INVOICE = {
    "number": "INV-1001",
    "items": [{"product": "تيشيرت قطن", "size": "M", "qty": 1, "price": "250"}],
}
_RETURNS = {"return": "الاسترجاع خلال 7 أيام بشرط المنتج بحالته والفاتورة."}
_EXCHANGE = {"exchange": "الاستبدال خلال 14 يوم من الشراء بشرط وجود الفاتورة."}
_PB_LATE = {
    "title": "الطلب اتأخر",
    "problem": "الطلب اتأخر ما وصلش التوصيل شحن",
    "steps": ["اطلب رقم الفاتورة", "وضّح إن التوصيل من يومين لخمسة أيام عمل"],
    "escalate_when": "لو عدت 5 أيام عمل",
}
_PB_WRONG_SIZE = {
    "title": "جاني مقاس غلط",
    "problem": "المقاس اللي وصلني غلط مش مظبوط على جسمي",
    "steps": ["اطلب رقم الفاتورة", "وضّح سياسة الاستبدال", "اقترح مقاس بديل متاح"],
    "escalate_when": "لو العميل رفض الاستبدال",
}
_NO_HANDOVER = {"handover": False, "tools_not_called": ("handover_to_human",)}

CASES: tuple[Case, ...] = (
    # ---- resolves by itself: product ------------------------------------------------------
    Case(
        id="self-details-of-a-named-product",
        category="handover_unwanted",
        risk="high",
        title="asks what sizes and prices a product has: look it up, answer fully",
        store=StoreFixture(products=(_TSHIRT, _JEANS)),
        turns=(
            Turn(
                "المقاسات والاسعار بتاعة التيشيرت القطن ايه؟",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_contains_all=("250",),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    Case(
        id="self-out-of-stock-offers-what-exists",
        category="handover_unwanted",
        risk="high",
        title="the size asked for is gone: say so and offer what IS available, no handover",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "عايز التيشيرت القطن مقاس XL",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_contains_any=("M", "L", "مش متاح", "خلص", "مفيش"),
                    reply_must_not_contain=("متاح XL", "XL متاح"),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    Case(
        id="self-product-that-does-not-exist",
        category="handover_unwanted",
        risk="high",
        title="asks for something the shop does not sell: say so, no handover, no invention",
        store=StoreFixture(products=(_TSHIRT,)),
        turns=(
            Turn(
                "عندكم جاكيت جلد؟",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_must_not_contain=("عندنا جاكيت", "الجاكيت متاح"),
                    min_reply_chars=20,
                ),
            ),
        ),
    ),
    Case(
        id="self-compares-two-of-our-products",
        category="handover_unwanted",
        risk="normal",
        title="'which is cheaper, the tee or the jeans': both are in the catalogue, so answer",
        store=StoreFixture(products=(_TSHIRT, _JEANS)),
        turns=(
            Turn(
                "ايه الارخص التيشيرت ولا الجينز؟",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_contains_all=("250", "600"),
                ),
            ),
        ),
    ),
    # ---- resolves by itself: policy -------------------------------------------------------
    Case(
        id="self-return-policy-quoted",
        category="store_policy",
        risk="high",
        title="return policy is written: quote it, do not send the customer to a person",
        store=StoreFixture(products=(_TSHIRT,), policies=_RETURNS),
        turns=(
            Turn(
                "ينفع ارجع المنتج لو معجبنيش؟",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("get_store_info",),
                    reply_contains_all=("7",),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    Case(
        id="self-exchange-inside-the-window",
        category="store_policy",
        risk="high",
        title="inside the written window: confirm what is written and what is needed",
        store=StoreFixture(products=(_TSHIRT,), policies=_EXCHANGE),
        turns=(
            Turn(
                "اشتريت من 5 ايام ومقاسي مظبوطش، ينفع استبدل؟",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("get_store_info",),
                    reply_contains_any=("الفاتورة",),
                    reply_must_not_contain=("مينفعش", "انتهت"),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    # ---- resolves by itself: invoice ------------------------------------------------------
    Case(
        id="self-exchange-uses-the-invoice-then-offers-a-size",
        category="invoice",
        risk="high",
        title="wants another size of what he bought: read the invoice, then check stock",
        store=StoreFixture(products=(_TSHIRT,), invoices=(_INVOICE,), policies=_EXCHANGE),
        turns=(
            Turn(
                "فاتورتي INV-1001 وعايز استبدل التيشيرت بمقاس L",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("get_my_orders",),
                    reply_contains_any=("L",),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    Case(
        id="self-asks-for-the-invoice-instead-of-handing-over",
        category="invoice",
        risk="high",
        title="an invoice question without a number: ask for the number, do not escalate",
        store=StoreFixture(products=(_TSHIRT,), invoices=(_INVOICE,)),
        turns=(
            Turn(
                "عايز اعرف اشتريت ايه المرة اللي فاتت",
                Expect(
                    **_NO_HANDOVER,
                    reply_contains_any=("رقم الفاتورة", "رقم فاتورة", "الفاتورة"),
                    min_reply_chars=20,
                ),
            ),
        ),
    ),
    # ---- resolves by itself: playbook -----------------------------------------------------
    Case(
        id="self-wrong-size-delivered-follows-the-playbook",
        category="problem",
        risk="high",
        title="a known problem with a playbook: follow it, ask for the invoice, no handover yet",
        store=StoreFixture(products=(_TSHIRT,), playbooks=(_PB_WRONG_SIZE,), policies=_EXCHANGE),
        turns=(
            Turn(
                "المقاس اللي وصلني غلط",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("find_support_playbook",),
                    reply_contains_any=("الفاتورة", "رقم"),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    Case(
        id="self-late-order-gives-the-playbook-timeline",
        category="problem",
        risk="high",
        title="late order inside the playbook's window: explain the timeline, do not escalate",
        store=StoreFixture(products=(_TSHIRT,), playbooks=(_PB_LATE,)),
        turns=(
            Turn(
                "الطلب اتأخر عليا ليه؟",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("find_support_playbook",),
                    reply_contains_any=("يومين", "خمسة", "5", "الفاتورة"),
                    min_reply_chars=25,
                ),
            ),
        ),
    ),
    Case(
        id="no-playbook-no-fabricated-fix",
        category="problem",
        risk="critical",
        title="a problem NO playbook covers: do not invent a procedure, hand over honestly",
        store=StoreFixture(products=(_TSHIRT,), playbooks=(_PB_LATE,)),
        turns=(
            Turn(
                "المنتج وصلني متقطع من جنب وفيه خيط طالع",
                Expect(
                    tools_called=("find_support_playbook",),
                    reply_must_not_contain=("هنبعتلك بدل", "هنرجعلك", "هنعوضك"),
                    min_reply_chars=25,
                ),
            ),
        ),
        rubric=(
            "No playbook matches a defective item, so the reply does not promise a replacement "
            "or refund; it acknowledges and routes the case to the team.",
        ),
    ),
    # ---- multi-turn: the conversation is the unit -----------------------------------------
    Case(
        id="flow-asks-then-narrows-then-resolves",
        category="product_info",
        risk="high",
        title="vague first message, the agent narrows it, the answer lands without a handover",
        store=StoreFixture(products=(_TSHIRT, _JEANS)),
        turns=(
            Turn(
                "عايز حاجة اشتريها",
                Expect(**_NO_HANDOVER, min_reply_chars=15),
            ),
            Turn(
                "تيشيرت مقاس L",
                Expect(
                    **_NO_HANDOVER,
                    tools_called=("search_catalog",),
                    reply_contains_all=("250",),
                ),
            ),
        ),
    ),
    Case(
        id="flow-policy-then-product-then-still-no-handover",
        category="store_policy",
        risk="high",
        title="three different questions in a row, each answered from its own source",
        store=StoreFixture(products=(_TSHIRT,), policies=_RETURNS),
        turns=(
            Turn(
                "الاسترجاع ازاي؟",
                Expect(**_NO_HANDOVER, tools_called=("get_store_info",), reply_contains_all=("7",)),
            ),
            Turn(
                "وسعر التيشيرت كام؟",
                Expect(
                    **_NO_HANDOVER, tools_called=("search_catalog",), reply_contains_all=("250",)
                ),
            ),
            Turn(
                "تمام شكرا",
                Expect(**_NO_HANDOVER, min_reply_chars=5),
            ),
        ),
    ),
    Case(
        id="flow-problem-solved-then-wants-a-person-anyway",
        category="handover_wanted",
        risk="critical",
        title="the agent helps, then the customer asks for a human: that request always wins",
        store=StoreFixture(products=(_TSHIRT,), playbooks=(_PB_LATE,)),
        turns=(
            Turn(
                "الطلب اتأخر",
                Expect(**_NO_HANDOVER, tools_called=("find_support_playbook",)),
            ),
            Turn(
                "لأ انا عايز اتكلم مع حد من الموظفين",
                Expect(handover=True, tools_called=("handover_to_human",)),
            ),
        ),
    ),
)
