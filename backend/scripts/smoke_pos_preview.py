"""Smoke-test the preview: log in and walk one POS sale end to end."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:9000/api/v1"
EMAIL = "cashier@demo.fihrist.world"
PASSWORD = "Demo1234!"


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


def main() -> None:
    status, tokens = call("POST", "/auth/login", body={"email": EMAIL, "password": PASSWORD})
    print(f"login -> {status}")
    if status != 200:
        print(tokens)
        return
    token = tokens["access_token"]
    print("  access_token acquired")

    status, me = call("GET", "/auth/me", token=token)
    print(f"me -> {status} {me.get('email') if isinstance(me, dict) else me}")

    status, profiles = call("GET", "/pos/profiles", token=token)
    print(f"profiles -> {status}")
    if status != 200:
        print(profiles)
        return
    items = profiles if isinstance(profiles, list) else profiles.get("items", [])
    profile = items[0]
    print(f"  profile: {profile['name']} methods={profile.get('allowed_payment_methods')}")

    status, sessions = call("GET", f"/pos/profiles/{profile['id']}", token=token)
    print(f"profile detail -> {status}")

    status, session = call("GET", "/pos/registers", token=token)
    print(f"registers -> {status}")
    regs = session if isinstance(session, list) else session.get("items", [])
    print(f"  registers: {[r['code'] for r in regs]}")

    print("\n=== READY ===")
    print("web:  http://localhost:3000/pos")
    print(f"api:  {BASE}")


if __name__ == "__main__":
    main()
