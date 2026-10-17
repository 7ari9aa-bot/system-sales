"""Seed a demo tenant + cashier data for the local POS preview.

Runs against whatever DATABASE_URL the process env carries (the preview points
it at the portable kasher DB on port 55432). Creates:

  * owner user:  cashier@demo.fihrist.world / Demo1234!
  * a POS profile with an open register + open cash session
  * a handful of sellable variants with barcodes so the scan box works

Idempotent: re-running reuses the existing tenant/user and just ensures one
open session exists.
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.db import bind_tenant, get_sessionmaker
from app.modules.catalog.models import Product, ProductIdentifier, ProductVariant
from app.modules.identity.models import Tenant, User
from app.modules.identity.services import auth as auth_service
from app.modules.inventory.service import InventoryService
from app.modules.pos.models import PosProfile, PosRegister, PosSession
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService

EMAIL = "cashier@demo.fihrist.world"
PASSWORD = "Demo1234!"
SLUG = "demo-store"

# (barcode, title, sku, price)
CATALOG_SEED = [
    ("6221000000017", "أرز مصري 1 كجم", "RICE-1KG", "34.50"),
    ("6221000000024", "زيت عافية 1 لتر", "OIL-1L", "79.00"),
    ("6221000000031", "سكر ناعم 1 كجم", "SUGAR-1KG", "28.75"),
    ("6221000000048", "شاي العروسة 250 جم", "TEA-250", "46.00"),
    ("6221000000055", "مياه معدنية 1.5 لتر", "WATER-1.5", "7.00"),
]


async def main() -> None:
    async with get_sessionmaker()() as session:
        # ---- owner + tenant -------------------------------------------------
        user = (await session.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none()
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == SLUG))).scalar_one_or_none()

        if user is None or tenant is None:
            user, tenant = await auth_service.AuthService.register(
                session,
                tenant_name="Demo Store",
                tenant_slug=SLUG,
                email=EMAIL,
                password=PASSWORD,
                full_name="Demo Cashier",
            )
            print(f"[new] tenant={tenant.id} user={user.id}")
        else:
            print(f"[reuse] tenant={tenant.id} user={user.id}")

        # verification is an email round-trip we cannot do locally — flip it
        if not user.email_verified:
            user.email_verified = True
        await session.commit()

        tenant_id = tenant.id
        owner_id = user.id

        # ---- catalog --------------------------------------------------------
        await bind_tenant(session, tenant_id)
        existing_product = (
            await session.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id, Product.slug == "grocery-basics"
                )
            )
        ).scalar_one_or_none()
        if existing_product is None:
            existing_product = Product(
                tenant_id=tenant_id,
                title="بقالة أساسية",
                slug="grocery-basics",
                status="active",
            )
            session.add(existing_product)
            await session.flush()
        await session.commit()

        variant_count = 0
        for barcode, title, sku, price in CATALOG_SEED:
            already = (
                await session.execute(
                    select(ProductIdentifier).where(
                        ProductIdentifier.tenant_id == tenant_id,
                        ProductIdentifier.value == barcode,
                    )
                )
            ).scalar_one_or_none()
            if already is not None:
                variant_count += 1
                continue
            variant = ProductVariant(
                tenant_id=tenant_id,
                product_id=existing_product.id,
                title=title,
                sku=sku,
                price=Decimal(price),
                is_active=True,
            )
            session.add(variant)
            await session.flush()
            session.add(
                ProductIdentifier(
                    tenant_id=tenant_id,
                    variant_id=variant.id,
                    type="barcode",
                    value=barcode,
                )
            )
            variant_count += 1
        await session.commit()
        print(f"catalog ready: {variant_count} sellable variants")

        # ---- warehouse (bootstraps 'Main' if the tenant has none) ------------
        await bind_tenant(session, tenant_id)
        warehouse = await InventoryService.get_default_warehouse(session, tenant_id)
        await session.commit()
        print(f"warehouse: {warehouse.code} ({warehouse.id})")

        # ---- POS profile ----------------------------------------------------
        await bind_tenant(session, tenant_id)
        profile = (
            await session.execute(
                select(PosProfile).where(PosProfile.tenant_id == tenant_id)
            )
        ).scalars().first()

        if profile is None:
            profile = await PosProfileService.create(
                session,
                tenant_id,
                name="Main Counter",
                code="MAIN",
                warehouse_id=warehouse.id,
                allowed_payment_methods=["cash", "card", "wallet", "bank_transfer"],
                discount_ceiling_pct="10",
            )
            await PosProfileService.grant_user(session, tenant_id, profile.id, owner_id)
            await session.commit()
            print(f"profile created: {profile.id}")
        else:
            print(f"profile reused: {profile.id}")

        # ---- register -------------------------------------------------------
        register = (
            await session.execute(
                select(PosRegister).where(
                    PosRegister.tenant_id == tenant_id, PosRegister.profile_id == profile.id
                )
            )
        ).scalars().first()
        if register is None:
            register = await PosService.create_register(
                session,
                tenant_id,
                name="Counter 1",
                code="C1",
                warehouse_id=warehouse.id,
                profile_id=profile.id,
            )
            await session.commit()
            print(f"register created: {register.id}")
        else:
            print(f"register reused: {register.id}")

        # ---- open session ---------------------------------------------------
        open_session = (
            await session.execute(
                select(PosSession).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.register_id == register.id,
                    PosSession.status == "OPEN",
                )
            )
        ).scalars().first()
        if open_session is None:
            open_session = await PosService.open_session(
                session,
                tenant_id,
                register.id,
                opening_float=Decimal("500.00"),
                opened_by=owner_id,
                profile_id=profile.id,
                cashier_user_id=owner_id,
            )
            await session.commit()
            print(f"session opened: {open_session.id}")
        else:
            print(f"session reused: {open_session.id}")

        print("\n=== PREVIEW CREDENTIALS ===")
        print(f"email:    {EMAIL}")
        print(f"password: {PASSWORD}")
        print(f"session:  {open_session.id}")
        print(f"barcode:  {CATALOG_SEED[0][0]}")


if __name__ == "__main__":
    asyncio.run(main())
