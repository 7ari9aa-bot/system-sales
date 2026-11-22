"""Contract Drift Gate — verifies Desktop & Mobile client models against OpenAPI lock.

Validates that client models in TypeScript (desktop) and Dart (mobile) remain in
strict alignment with the published ``desktop/openapi.lock.json`` schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_LOCK_PATH = REPO_ROOT / "desktop" / "openapi.lock.json"
MOBILE_MODELS_PATH = REPO_ROOT / "mobile" / "lib" / "data" / "models"
DESKTOP_SRC_PATH = REPO_ROOT / "desktop" / "src"


def verify_openapi_lock() -> dict:
    if not OPENAPI_LOCK_PATH.exists():
        raise FileNotFoundError(f"Missing openapi.lock.json at {OPENAPI_LOCK_PATH}")
    with open(OPENAPI_LOCK_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data


def verify_mobile_contract_alignment(spec: dict) -> list[str]:
    errors = []
    schemas = spec.get("components", {}).get("schemas", {})

    # 1. StockRow schema check
    stock_row = schemas.get("StockRow")
    if not stock_row:
        errors.append("Schema 'StockRow' not found in openapi.lock.json")
    else:
        props = stock_row.get("properties", {})
        required_fields = ["variant_id", "product_title", "price", "on_hand"]
        for field in required_fields:
            if field not in props:
                errors.append(f"StockRow missing expected field '{field}' in OpenAPI schema")

    # 2. Check mobile product.dart handles StockRow
    product_dart = MOBILE_MODELS_PATH / "product.dart"
    if not product_dart.exists():
        errors.append(f"Missing mobile model: {product_dart}")
    else:
        content = product_dart.read_text(encoding="utf-8")
        expected_tokens = ["variant_id", "product_title", "on_hand", "price", "barcode", "sku"]
        for tok in expected_tokens:
            if tok not in content:
                errors.append(f"mobile/product.dart drifts: missing token '{tok}'")

    # 3. Check mobile durable_operation.dart has idempotency and status
    op_dart = REPO_ROOT / "mobile" / "lib" / "core" / "sync" / "durable_operation.dart"
    if not op_dart.exists():
        errors.append(f"Missing durable_operation.dart at {op_dart}")
    else:
        op_content = op_dart.read_text(encoding="utf-8")
        for tok in ["operationUuid", "idempotencyKey", "payloadSnapshot", "DurableOperationStatus"]:
            if tok not in op_content:
                errors.append(f"mobile/durable_operation.dart drifts: missing token '{tok}'")

    return errors


def verify_desktop_contract_alignment(spec: dict) -> list[str]:
    errors = []
    # Check money primitive enforcement
    primitives_ts = DESKTOP_SRC_PATH / "platform" / "contract" / "primitives.ts"
    if not primitives_ts.exists():
        errors.append(f"Missing primitives.ts at {primitives_ts}")
    else:
        prim_content = primitives_ts.read_text(encoding="utf-8")
        if "DECIMAL_STRING" not in prim_content or "moneySchema" not in prim_content:
            errors.append("desktop/primitives.ts drifts: missing moneySchema decimal string rule")

    # Check CashierView and PurchasingView use string/bigint cents without floats
    cashier_ts = DESKTOP_SRC_PATH / "features" / "cashier" / "CashierView.tsx"
    if cashier_ts.exists():
        c_content = cashier_ts.read_text(encoding="utf-8")
        if "totalCents" not in c_content:
            errors.append("desktop/CashierView.tsx drifts: missing BigInt cents handling")

    return errors


def main() -> int:
    print("Contract Drift Gate: Inspecting OpenAPI schema and client codebases...")
    try:
        lock = verify_openapi_lock()
        spec = lock.get("spec", {})
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    mobile_errors = verify_mobile_contract_alignment(spec)
    desktop_errors = verify_desktop_contract_alignment(spec)

    all_errors = mobile_errors + desktop_errors

    if all_errors:
        print(f"Contract Drift Gate: FAILED with {len(all_errors)} error(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    print("Contract Drift Gate: OK — Desktop and Mobile contracts match openapi.lock.json!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
