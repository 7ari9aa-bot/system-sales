"""Seed a demo tenant with realistic data through the REAL services.

Idempotent: re-running skips if the demo tenant already exists.

    .venv/bin/python scripts/seed_demo.py

Creates: demo@salesos-demo.com (password: Demo-1234) / tenant "متجر الديمو"
with products, inventory, customers, conversations, and orders placed via
OrderService (exercising reservation + outbox for real).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa

from app.core.db import SessionLocal, bind_tenant
from app.modules.catalog.service import CatalogService
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.identity.models import Role, Tenant
from app.modules.identity.service import AuthService
from app.modules.inventory.service import InventoryService
from app.modules.marketing.service import MarketingService
from app.modules.orders.service import OrderService


async def main() -> int:
    async with SessionLocal() as session:
        async with session.begin():
            demo = (
                await session.execute(
                    sa.select(Tenant).where(Tenant.slug == "demo-store")
                )
            ).scalar_one_or_none()
            if demo is not None:
                print("demo tenant already exists — nothing to do")
                return 0

            # 1) tenant + owner via the real register flow
            user, tenant = await AuthService.register(
                session,
                tenant_name="متجر الديمو",
                tenant_slug="demo-store",
                email="demo@salesos-demo.com",
                password="Demo-1234",
                full_name="مالك المتجر",
            )
            await bind_tenant(session, tenant.id)
            print(f"tenant {tenant.slug} owner={user.email} (login: Demo-1234)")

            owner_role = (
                await session.execute(sa.select(Role).where(Role.code == "owner"))
            ).scalar_one()
            _ = owner_role  # register already bound membership

            # 2) catalog + inventory
            products_spec = [
                ("تيشيرت قطن رجالي", "TSHIRT-M", "149.99"),
                ("هودي شتوي", "HOODIE-L", "299.00"),
                ("مومز جينز", "JEANS-32", "349.50"),
                ("كاب صيفي", "CAP-01", "89.00"),
                ("شنطة ظهر", "BAG-BK", "425.00"),
            ]
            variant_ids = {}
            warehouse = None
            from app.modules.inventory.models import Warehouse

            warehouse = Warehouse(tenant_id=tenant.id, name="المخزن الرئيسي", code="MAIN")
            session.add(warehouse)
            await session.flush()


            for title, sku, price in products_spec:
                product = await CatalogService.create_product(
                    session,
                    tenant.id,
                    title=title,
                    slug=f"demo-{sku.lower()}",
                )
                product.status = "active"  # demo products are live immediately
                variant = await CatalogService.add_variant(
                    session,
                    tenant.id,
                    product.id,
                    sku=sku,
                    title="مقاس واحد",
                    price=Decimal(price),
                )
                variant_ids[sku] = variant.id
                await InventoryService.move(
                    session,
                    tenant.id,
                    variant.id,
                    warehouse.id,
                    direction="in",
                    quantity=40,
                    reason="purchase",
                )

            # 3) customers
            customers_spec = [
                ("أحمد محمود", "201001234567"),
                ("سارة إبراهيم", "201098765432"),
                ("منى عبد الله", "201155566778"),
            ]
            customer_ids = {}
            for name, phone in customers_spec:
                customer = await CustomerService.get_or_create_by_identity(
                    session, tenant.id,
                    channel="whatsapp", external_id=phone, name=name, phone=phone
                )
                customer_ids[name] = customer.id

            # 4) conversations with messages
            convo = await ConversationService.get_or_create(
                session, tenant.id, customer_id=customer_ids["أحمد محمود"], channel="whatsapp"
            )
            await ConversationService.add_message(
                session, tenant.id, conversation_id=convo.id,
                direction="inbound", sender_type="customer",
                body="عندك مقاس L من الهودي؟", channel_message_id=f"seed-{uuid.uuid4().hex[:8]}",
            )
            await ConversationService.add_message(
                session, tenant.id, conversation_id=convo.id,
                direction="outbound", sender_type="agent",
                body="أيوة متوفر! السعر 299 جنيه وشحن لحد الباب.",
            )
            convo2 = await ConversationService.get_or_create(
                session, tenant.id, customer_id=customer_ids["سارة إبراهيم"], channel="whatsapp"
            )
            await ConversationService.add_message(
                session, tenant.id, conversation_id=convo2.id,
                direction="inbound", sender_type="customer",
                body="عايزة أتابع طلبي",
                channel_message_id=f"seed-{uuid.uuid4().hex[:8]}",
            )

            # 5) orders via the REAL service (reservation + snapshots + outbox)
            orders_spec = [
                ("أحمد محمود", [("HOODIE-L", 1)]),
                ("سارة إبراهيم", [("TSHIRT-M", 2), ("CAP-01", 1)]),
                ("منى عبد الله", [("BAG-BK", 1)]),
            ]
            for name, items in orders_spec:
                order = await OrderService.create_order(
                    session,
                    tenant.id,
                    customer_ids[name],
                    [{"variant_id": variant_ids[sku], "quantity": qty} for sku, qty in items],
                    channel="whatsapp",
                )
                await OrderService.add_payment(
                    session, tenant.id, order.id, method="cod", amount=order.grand_total
                )
                print(f"order {order.number} total={order.grand_total}")

            # 6) marketing: campaign + touchpoints + conversion
            campaign = await MarketingService.create_campaign(
                session, tenant.id, name="حملة رمضان", provider="facebook", budget=Decimal("1000")
            )
            for name, _phone in customers_spec:
                await MarketingService.record_touchpoint(
                    session, tenant.id, customer_id=customer_ids[name],
                    source="facebook", medium="cpc", campaign_id=campaign.id,
                    click_id=f"fbseed-{uuid.uuid4().hex[:6]}",
                )
            await MarketingService.record_conversion(
                session, tenant.id, customer_id=customer_ids["أحمد محمود"],
                type="purchase", value=Decimal("299.00"),
                occurred_at=datetime.now(UTC),
            )
            await MarketingService.record_conversion(
                session, tenant.id, customer_id=customer_ids["سارة إبراهيم"],
                type="purchase", value=Decimal("387.50"),
                occurred_at=datetime.now(UTC) - timedelta(days=3),
            )
            print("marketing seeded")

    print("\nDEMO READY → login: demo@salesos-demo.com / Demo-1234")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
