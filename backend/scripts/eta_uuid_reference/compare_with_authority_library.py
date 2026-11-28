"""Compare our UUID with the authority's OWN library on many REAL receipts from our builder."""

import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.applications.apparel.modules.einvoice.providers.eta import builder
from app.applications.apparel.modules.einvoice.providers.eta.codes import BuyerType, ReceiptType, ReturnReason
from app.applications.apparel.modules.einvoice.providers.eta.models import BuyerProfile, DiscountSpec
from tests.test_eta_ereceipt_core import _line, _receipt, _seller

rnd = random.Random(20261120)
NAMES = [
    "قميص قطن",
    "بنطلون جينز",
    'Shirt "slim" fit',
    "جاكيت & معطف <شتوي>",
    "حذاء\tرياضي",
    "ça va é ñ 😀",
    "back\\slash",
    "x" * 120,
    "ctl\x01\x1f\x7f end",
    "line\nbreak\r\n",
    "sep\u2028\u2029x",
    '\\\\""',
    "",
    " ",
    "مرتجع «خاص» ٣٤٥",
]


def money(lo, hi):
    return D(str(round(rnd.uniform(lo, hi), rnd.choice([0, 1, 2, 3, 5]))))


def make(i):
    lines = []
    for k in range(rnd.randint(1, 6)):
        kw = dict(
            internal_code=f"SKU{i}-{k}",
            description=rnd.choice(NAMES),
            item_code=f"EG-674859545-{rnd.randint(1, 99999)}",
            quantity=money(0.001, 12),
            unit_price=money(1, 4000),
        )
        if rnd.random() < 0.3:
            kw["item_type"] = "GS1"
            kw["item_code"] = "".join(rnd.choice("0123456789") for _ in range(13))
        if rnd.random() < 0.3:
            kw["commercial_discounts"] = (DiscountSpec(amount=money(0, 5), description="خصم"),)
        if rnd.random() < 0.3:
            kw["item_discounts"] = (DiscountSpec(amount=money(0, 5), description="item"),)
        lines.append(_line(**kw))
    kind = rnd.choice(["sale", "sale", "return", "rwr"])
    kw = dict(
        receipt_number=f"R-{i}",
        lines=tuple(lines),
        issued_at=datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
        + timedelta(seconds=rnd.randint(0, 99999)),
        previous_uuid=rnd.choice(["", "".join(rnd.choice("0123456789abcdef") for _ in range(64))]),
        seller=_seller(rin=str(rnd.randint(100000000, 999999999))),
    )
    if rnd.random() < 0.4:
        kw["buyer"] = BuyerProfile(
            type=BuyerType.BUSINESS,
            id=str(rnd.randint(10**8, 10**9)),
            name=rnd.choice(NAMES),
            mobile_number="01012345678",
        )
    if kind == "return":
        kw.update(
            receipt_type=ReceiptType.RETURN,
            reference_uuid="".join(rnd.choice("0123456789abcdef") for _ in range(64)),
        )
    if kind == "rwr":
        kw.update(
            receipt_type=ReceiptType.RETURN_WITHOUT_REFERENCE,
            return_reason=ReturnReason.BEFORE_ADOPTION,
            sales_issued_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
        )
        if rnd.random() < 0.5:
            kw["reference_uuid"] = "".join(rnd.choice("0123456789abcdef") for _ in range(64))
    return _receipt(**kw)


N = int(sys.argv[1])
docs = [builder.build_receipt(make(i)) for i in range(N)]
# the official procedure: the receipt as it will be sent, with ``uuid`` left EMPTY
sent = [builder.dumps({**d, "header": {**d["header"], "uuid": ""}}) for d in docs]
out = subprocess.run(
    ["dotnet", "Runner.dll"], input="\n".join(sent) + "\n", capture_output=True, text=True
)
official = out.stdout.strip().split("\n")
assert len(official) == N, (len(official), out.stderr[:300])
bad = [
    (i, d["header"]["uuid"], o)
    for i, (d, o) in enumerate(zip(docs, official, strict=True))
    if d["header"]["uuid"] != o
]
kinds = {}
for d in docs:
    kinds[d["documentType"]["receiptType"]] = kinds.get(d["documentType"]["receiptType"], 0) + 1
print(
    f"{N} receipts {kinds}: {N - len(bad)} identical to the authority's own library,"
    f" {len(bad)} different"
)
for i, mine, off in bad[:3]:
    print(" first difference:", i, mine[:16], off[:16])
