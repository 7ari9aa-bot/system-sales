"""Golden evaluation harness (spec §17.2) — plant, compute, assert. NO LLM.

    .venv/bin/python scripts/run_golden_eval.py [--seed 42]

Creates a throwaway tenant (golden-eval-<hex>), seeds each of the seven
synthetic stores, and runs the REAL analytics path over each one via
evaluate_scenario — the same compiler/capabilities/drivers production uses.
One verdict line per scenario; exit 0 only when every check passes.

No model calls, no API keys: fully deterministic end to end. This is the
gate to re-run whenever the commerce read schema changes — including the
Commerce Core refactor, whose read surface (placed/delivered/paid/
processed semantics) these scenarios pin.

The seeding lives HERE, not in the test suite, so the operator harness and
the test matrix plant data through ONE code path — the tests import
seed_store from this script (the test_railway_deploy_preflight precedent).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _bootstrap import load_settings, session_factory  # noqa: E402

from app.core.db import bind_tenant  # noqa: E402
from app.modules.analytics.evaluation.golden import evaluate_scenario  # noqa: E402
from app.modules.analytics.evaluation.synthetic import (  # noqa: E402
    Scenario,
    SyntheticStore,
    generate_store,
)
from app.modules.customers.models import Customer  # noqa: E402
from app.modules.orders.models import Order, OrderPayment, Refund, Shipment  # noqa: E402


async def seed_store(
    session,  # AsyncSession — annotated loosely: scripts import after bootstrap
    tenant_id: uuid.UUID,
    store: SyntheticStore,
) -> None:
    """Map the synthetic generator's rows onto the real commerce tables.

    Order numbers get a random suffix: the generator's ids are only unique
    within one store, and an eval tenant may accumulate several runs.
    """
    customer = Customer(tenant_id=tenant_id, name="Synthetic Customer")
    session.add(customer)
    await session.flush()
    order_ids: dict[str, uuid.UUID] = {}
    for order in store.orders:
        row = Order(
            tenant_id=tenant_id,
            number=f"{order['number']}-{uuid.uuid4().hex[:6]}",
            customer_id=customer.id,
            status=order["status"],
            grand_total=order["grand_total"],
            channel=order["channel"],
            placed_at=datetime.fromisoformat(order["placed_at"]),
        )
        session.add(row)
        order_ids[order["id"]] = row
    await session.flush()  # ids assigned before shipments/payments reference them
    for shipment in store.shipments:
        session.add(
            Shipment(
                tenant_id=tenant_id,
                order_id=order_ids[shipment["order_id"]].id,
                carrier=shipment["carrier"],
                status=shipment["status"],
                shipped_at=datetime.fromisoformat(shipment["shipped_at"]),
                delivered_at=datetime.fromisoformat(shipment["delivered_at"]),
            )
        )
    payment_rows: dict[str, OrderPayment] = {}
    for payment in store.payments:
        row = OrderPayment(
            tenant_id=tenant_id,
            order_id=order_ids[payment["order_id"]].id,
            method=payment["method"],
            status=payment["status"],
            amount=payment["amount"],
            paid_at=datetime.fromisoformat(payment["paid_at"]),
        )
        session.add(row)
        payment_rows[payment["id"]] = row
    await session.flush()
    for refund in store.refunds:
        session.add(
            Refund(
                tenant_id=tenant_id,
                payment_id=payment_rows[refund["payment_id"]].id,
                amount=refund["amount"],
                status=refund["status"],
                processed_at=datetime.fromisoformat(refund["processed_at"]),
            )
        )
    await session.flush()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden evaluation harness")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = load_settings(script="run_golden_eval.py")
    if settings.environment == "production":
        print("refusing to create eval tenants in a production environment")
        return 1

    factory = session_factory()
    # Tenant + owner through the REAL register flow: RLS policies verify
    # membership, so a bare Tenant row cannot seed its own store.
    from app.modules.identity.service import AuthService

    async def _fresh_tenant(session) -> uuid.UUID:
        _user, tenant = await AuthService.register(
            session,
            tenant_name="Golden Eval",
            tenant_slug=f"golden-eval-{uuid.uuid4().hex[:8]}",
            email=f"eval-{uuid.uuid4().hex[:8]}@golden-eval.test",
            password=uuid.uuid4().hex + "-Golden!",
            full_name="Golden Eval Operator",
        )
        return tenant.id

    scenarios_run: list[tuple[str, bool, uuid.UUID, list[tuple[str, bool, str]]]] = []
    for scenario in Scenario:
        # A FRESH tenant per scenario: the scenarios share the same fixed
        # date windows, so two stores in one tenant would contaminate each
        # other's facts (the test matrix gets this isolation for free from
        # its per-test transaction). One transaction per scenario, matching
        # bind_tenant's transaction-scoped GUC.
        async with factory() as session:
            tenant_id = await _fresh_tenant(session)
            await bind_tenant(session, tenant_id)
            store = generate_store(scenario, seed=args.seed)
            await seed_store(session, tenant_id, store)
            result = await evaluate_scenario(session, tenant_id, store)
            await session.commit()  # keep each scenario's data for forensics
        scenarios_run.append((scenario.value, result.passed, tenant_id, result.checks))

    failures = 0
    print(f"seed={args.seed}")
    for name, passed, tenant_id, checks in scenarios_run:
        verdict = "PASS" if passed else "FAIL"
        ok_count = sum(ok for _n, ok, _d in checks)
        print(f"{verdict}  {name}  ({ok_count}/{len(checks)} checks)  tenant={tenant_id}")
        for check_name, ok, detail in checks:
            mark = "ok  " if ok else "FAIL"
            print(f"    [{mark}] {check_name}: {detail}")
        if not passed:
            failures += 1
    if failures:
        print(f"\n{failures} scenario(s) FAILED")
        return 1
    print(f"\nall {len(scenarios_run)} scenarios passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
