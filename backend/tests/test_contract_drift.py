"""Test Contract Drift Gate between backend OpenAPI lock, desktop and mobile clients."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_LOCK_PATH = REPO_ROOT / "desktop" / "openapi.lock.json"
MOBILE_MODELS_PATH = REPO_ROOT / "mobile" / "lib" / "data" / "models"
DESKTOP_SRC_PATH = REPO_ROOT / "desktop" / "src"


def test_openapi_lock_exists_and_has_valid_schemas() -> None:
    assert OPENAPI_LOCK_PATH.exists(), f"Missing openapi.lock.json at {OPENAPI_LOCK_PATH}"
    data = json.loads(OPENAPI_LOCK_PATH.read_text(encoding="utf-8"))
    assert "spec" in data
    assert "components" in data["spec"]
    schemas = data["spec"]["components"]["schemas"]
    assert "StockRow" in schemas, "StockRow schema must exist in openapi.lock.json"
    assert "variant_id" in schemas["StockRow"]["properties"]
    assert "product_title" in schemas["StockRow"]["properties"]
    assert "price" in schemas["StockRow"]["properties"]
    assert "on_hand" in schemas["StockRow"]["properties"]


def test_mobile_models_match_openapi_schemas() -> None:
    product_dart = MOBILE_MODELS_PATH / "product.dart"
    assert product_dart.exists()
    content = product_dart.read_text(encoding="utf-8")
    for field in ["variant_id", "product_title", "on_hand", "price", "barcode", "sku"]:
        assert field in content, f"mobile/product.dart must support field {field}"

    op_dart = REPO_ROOT / "mobile" / "lib" / "core" / "sync" / "durable_operation.dart"
    assert op_dart.exists()
    op_content = op_dart.read_text(encoding="utf-8")
    for field in ["operationUuid", "idempotencyKey", "payloadSnapshot", "DurableOperationStatus"]:
        assert field in op_content, f"mobile/durable_operation.dart must support {field}"


def test_desktop_contract_enforces_money_string_rule() -> None:
    primitives_ts = DESKTOP_SRC_PATH / "platform" / "contract" / "primitives.ts"
    assert primitives_ts.exists()
    content = primitives_ts.read_text(encoding="utf-8")
    assert "moneySchema" in content
    assert "DECIMAL_STRING" in content
