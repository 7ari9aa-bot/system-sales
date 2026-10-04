"""End-to-end Sales Intelligence demo — real model, synthetic store, no mocks.

    .venv/bin/python scripts/e2e_si_demo.py

Creates a demo tenant, configures the SI agent (Novita/GLM via model_configs),
seeds a synthetic store with planted truth (the Phase 2 generator), then runs
ONE real question through the platform runner with the REAL model. Proves the
whole chain: question → GLM → SI tools → compiler → evidence → grounded answer.

Requires NOVITA_API_KEY in the environment (or backend/.env). Costs a few
real inference calls — by design: this is the integration proof.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _bootstrap import session_factory  # noqa: E402

from app.core.db import bind_tenant  # noqa: E402
from app.core.model_registry import Base  # noqa: F401 — full metadata for FKs
from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.modules.analytics.evaluation.synthetic import Scenario, generate_store
from app.modules.customers.models import Customer
from app.modules.identity.models import Tenant
from app.modules.orders.models import Order, OrderPayment, Shipment


async def seed_synthetic_store(session, tenant_id: uuid.UUID) -> int:
    """Map the synthetic generator's rows onto the real orders tables."""
    store = generate_store(Scenario.BASELINE, seed=7, days=45)

    async def _customer(name: str) -> uuid.UUID:
        row = Customer(tenant_id=tenant_id, name=name)
        session.add(row)
        await session.flush()
        return row.id

    customer_ids = [await _customer(f"Demo Customer {i}") for i in range(8)]
    order_ids: dict[int, uuid.UUID] = {}
    for index, order in enumerate(store.orders):
        row = Order(
            tenant_id=tenant_id,
            number=f"DEMO-{index:05d}",
            customer_id=customer_ids[index % len(customer_ids)],
            status=order["status"],
            grand_total=order["grand_total"],
            channel=order["channel"],
            placed_at=datetime.fromisoformat(order["placed_at"]),
        )
        session.add(row)
        order_ids[index] = row
        if index % 20 == 19:
            await session.flush()
    await session.flush()

    for shipment in store.shipments:
        synthetic_order_id = int(shipment["order_id"].split("-")[-1]) - 1
        session.add(
            Shipment(
                tenant_id=tenant_id,
                order_id=order_ids[synthetic_order_id].id,
                carrier="Demo Carrier",
                status=shipment["status"],
                shipped_at=datetime.fromisoformat(shipment["shipped_at"]),
                delivered_at=datetime.fromisoformat(shipment["delivered_at"]),
            )
        )
    for payment in store.payments:
        synthetic_order_id = int(payment["order_id"].split("-")[-1]) - 1
        session.add(
            OrderPayment(
                tenant_id=tenant_id,
                order_id=order_ids[synthetic_order_id].id,
                method="cod",
                status="captured",
                amount=payment["amount"],
                paid_at=datetime.fromisoformat(payment["paid_at"]),
            )
        )
    await session.flush()
    return len(store.orders)


async def main() -> int:
    key = os.environ.get("NOVITA_API_KEY") or ""
    if not key:
        print("set NOVITA_API_KEY in the environment (or backend/.env)")
        return 2

    from scripts.configure_si import configure_agent

    factory = session_factory()
    async with factory() as session:
        tenant = Tenant(name="SI Demo Tenant", slug=f"si-demo-{uuid.uuid4().hex[:8]}")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id
        await bind_tenant(session, tenant_id)

        agent_id = await configure_agent(session, tenant_id, api_key=key)
        order_count = await seed_synthetic_store(session, tenant_id)
        await session.commit()

    print(f"tenant={tenant_id} agent={agent_id} orders={order_count}")
    print("running the REAL analysis (calls GLM)...")

    from app.modules.ai.gateway import AIGateway
    from app.modules.ai.runtime import AgentRunner

    async with session_factory()() as analysis_session:
        await bind_tenant(analysis_session, tenant_id)
        result = await run_sales_analysis(
            analysis_session,
        tenant_id,
        agent_id=agent_id,
        question="كام مبيعاتي آخر 30 يوم؟ وليه اتغيرت عن الشهر اللي قبله؟",
        runner=AgentRunner(gateway=AIGateway()),
    )

    print(f"\noutcome: {result.outcome.value}")
    print(f"answer:\n{result.answer}\n")
    print(f"findings: {len(result.findings)}")
    for finding in result.findings:
        print(f"  [{finding.confidence}] {finding.statement}")
    print(f"facts: {len(result.facts)}, evidence_hash: {result.evidence_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
