"""Drive one complete POS sale against the running preview API.

Proves the live stack: scan -> quote -> sell (cash) -> receipt -> reconciliation.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:9000/api/v1"
EMAIL = "cashier@demo.fihrist.world"
PASSWORD = "Demo1234!"
BARCODE = "6221000000017"


def call(method: str, path: str, *, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def show(label: str, status: int, payload) -> None:
    marker = "OK " if status < 300 else "ERR"
    print(f"[{marker}] {label} -> {status}")
    if status >= 300:
        print(f"       {json.dumps(payload)[:300]}")


def main() -> None:
    _, tokens = call("POST", "/auth/login", body={"email": EMAIL, "password": PASSWORD})
    token = tokens["access_token"]

    _, profiles = call("GET", "/pos/profiles", token=token)
    items = profiles if isinstance(profiles, list) else profiles.get("items", [])
    _profile = items[0]  # the walk's acting profile; unused inline

    _, sessions = call("GET", "/pos/registers", token=token)
    regs = sessions if isinstance(sessions, list) else sessions.get("items", [])
    register = regs[0]

    # find the open session for this register
    status, reg_detail = call("GET", f"/pos/registers/{register['id']}", token=token)
    print(f"register detail -> {status}")

    # list sessions via the register's sessions listing is not exposed; the
    # seeded session id was printed at seed time. Discover it via reconciliation
    # is also awkward, so ask the DB-backed endpoint that lists profiles' data.
    # Fall back: the seed printed the session; here we re-derive by scanning.
    status, rows = call("GET", f"/pos/sessions/{SESSION_ID}", token=token)
    show("session", status, rows)
    if status >= 300:
        return

    # 1) scan
    status, scan = call(
        "POST",
        f"/pos/sessions/{SESSION_ID}/scan",
        token=token,
        body={"identifier_type": "barcode", "value": BARCODE},
    )
    show("scan", status, scan)

    # 2) quote
    lines = [{"variant_id": scan["variant_id"], "quantity": "2"}] if status < 300 else []
    status, quote = call(
        "POST",
        f"/pos/sessions/{SESSION_ID}/quote",
        token=token,
        body={"items": lines},
    )
    show("quote", status, quote)
    if status >= 300:
        return
    total = quote.get("grand_total")
    print(f"       grand_total = {total}")

    # 3) sell — cash, exact change
    status, sale = call(
        "POST",
        f"/pos/sessions/{SESSION_ID}/sell",
        token=token,
        body={
            "items": lines,
            "tenders": [{"method": "cash", "amount": str(total)}],
        },
    )
    show("sell", status, sale)
    if status >= 300:
        return
    print(f"       order = {sale.get('order_id')}  receipt = {sale.get('receipt_number')}")

    # 4) reconciliation
    status, recon = call("GET", f"/pos/sessions/{SESSION_ID}/reconciliation", token=token)
    show("reconciliation", status, recon)
    if status < 300:
        print(f"       {json.dumps(recon)[:400]}")


SESSION_ID = "19ea246d-4f53-4dfb-8bfb-5e2919dc5cd1"

if __name__ == "__main__":
    main()
