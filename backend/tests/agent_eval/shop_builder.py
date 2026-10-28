"""Turn a case's ``StoreFixture`` into real rows, using the same services production uses.

Nothing here is mocked: products go through ``CatalogService``, stock through
``InventoryService``, policies through ``save_policy``, so what the agent's tools read is
what a real merchant's data looks like. Anything the fixture does not list does not exist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text

from app.modules.ai.models import KnowledgeItem, SupportPlaybook
from app.modules.ai.policies import save_policy
from app.modules.catalog.service import CatalogService
from app.modules.inventory.service import InventoryService
from app.modules.pos.service import PosService
from tests._pos_sell import sell
from tests.agent_eval.case_schema import StoreFixture


@dataclass
class BuiltShop:
    # invoice number the case wrote -> the number the shop actually issued
    invoice_numbers: dict[str, str] = field(default_factory=dict)
    product_ids: dict[str, uuid.UUID] = field(default_factory=dict)


async def build_shop(db, tenant_id: uuid.UUID, fixture: StoreFixture) -> BuiltShop:
    built = BuiltShop()
    warehouse = await InventoryService.get_default_warehouse(db, tenant_id)
    variants: dict[tuple[str, str], object] = {}

    for spec in fixture.products:
        product = await CatalogService.create_product(
            db, tenant_id, title=spec["title"], slug=f"p-{uuid.uuid4().hex[:10]}"
        )
        product = await CatalogService.update_product(db, tenant_id, product.id, status="active")
        built.product_ids[spec["title"]] = product.id
        for v in spec["variants"]:
            variant = await CatalogService.add_variant(
                db,
                tenant_id,
                product.id,
                title=v["size"],
                option_values={"size": v["size"]},
                price=v["price"],
            )
            variants[(spec["title"], v["size"])] = variant
            if v["stock"]:
                await InventoryService.move(
                    db,
                    tenant_id,
                    variant.id,
                    warehouse.id,
                    direction="in",
                    quantity=v["stock"],
                    reason="purchase",
                )

    for key, content in fixture.policies.items():
        await save_policy(db, tenant_id, key, content)

    for title, content in fixture.store_info.items():
        db.add(
            KnowledgeItem(
                tenant_id=tenant_id,
                title=title,
                content=content,
                source_type="text",
                status="ready",
                visibility="customer_facing",
            )
        )

    for pb in fixture.playbooks:
        db.add(
            SupportPlaybook(
                tenant_id=tenant_id,
                title=pb["title"],
                problem=pb["problem"],
                steps=list(pb["steps"]),
                escalate_when=pb["escalate_when"],
                is_active=True,
            )
        )

    if fixture.invoices:
        register = await PosService.create_register(
            db,
            tenant_id,
            name="كاشير",
            code=f"REG-{uuid.uuid4().hex[:6]}",
            warehouse_id=warehouse.id,
        )
        till = await PosService.open_session(db, tenant_id, register.id)
        for invoice in fixture.invoices:
            items = [
                {
                    "variant_id": str(variants[(i["product"], i["size"])].id),
                    "quantity": i["qty"],
                }
                for i in invoice["items"]
            ]
            sold = await sell(db, tenant_id, till.id, items=items)
            number = (
                await db.execute(
                    text("SELECT number FROM orders WHERE id = :i"), {"i": sold["order_id"]}
                )
            ).scalar_one()
            built.invoice_numbers[invoice["number"]] = number

    await db.flush()
    _ = select  # keep the import for callers that extend the builder
    return built
