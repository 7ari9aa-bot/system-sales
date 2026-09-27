"""Financial API router (V12 Wave C §31)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.modules.financial import schemas
from app.modules.financial.models import (
    ChartOfAccount,
    FinancialEntry,
    FinancialTransaction,
)
from app.modules.financial.service import FinancialService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/financial", tags=["financial"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]


def _account_dict(acc: ChartOfAccount) -> dict:
    return {
        "account_id": acc.account_id,
        "tenant_id": acc.tenant_id,
        "code": acc.code,
        "name": acc.name,
        "account_type": acc.account_type,
        "currency": acc.currency,
        "is_active": acc.is_active,
        "created_at": acc.created_at,
    }


def _tx_dict(tx: FinancialTransaction) -> dict:
    entries = []
    total_debits = Decimal("0.0000")
    total_credits = Decimal("0.0000")

    for e in tx.entries:
        amt = Decimal(str(e.amount))
        if e.entry_type == "DEBIT":
            total_debits += amt
        else:
            total_credits += amt

        entries.append(
            {
                "entry_id": e.entry_id,
                "account_id": e.account_id,
                "account_code": e.account.code if getattr(e, "account", None) else None,
                "entry_type": e.entry_type,
                "amount": amt,
                "memo": e.memo,
            }
        )

    return {
        "transaction_id": tx.transaction_id,
        "tenant_id": tx.tenant_id,
        "reference_type": tx.reference_type,
        "reference_id": tx.reference_id,
        "decision_id": tx.decision_id,
        "effect_id": tx.effect_id,
        "currency": tx.currency,
        "status": tx.status,
        "description": tx.description,
        "posted_at": tx.posted_at,
        "entries": entries,
        "total_debits": total_debits,
        "total_credits": total_credits,
    }


@router.get("/accounts", response_model=schemas.AccountListOut)
async def list_accounts(ctx: TenantCtxDep):
    """List chart of accounts for the tenant."""
    rows = (
        await ctx.session.execute(
            select(ChartOfAccount)
            .where(ChartOfAccount.tenant_id == ctx.tenant_id)
            .order_by(ChartOfAccount.code)
        )
    ).scalars().all()

    return {
        "items": [_account_dict(r) for r in rows],
        "total": len(rows),
    }


@router.post("/accounts", response_model=schemas.AccountOut, status_code=201)
async def create_account(ctx: WriteCtx, body: schemas.AccountCreate):
    """Create a new general ledger account in the chart of accounts."""
    acc = await FinancialService.create_account(
        ctx.session,
        ctx.tenant_id,
        code=body.code,
        name=body.name,
        account_type=body.account_type,
        currency=body.currency,
    )
    return _account_dict(acc)


@router.post("/accounts/seed-default", response_model=schemas.AccountListOut)
async def seed_default_accounts(ctx: WriteCtx):
    """Seed standard accounts if missing."""
    seeded = await FinancialService.seed_default_chart_of_accounts(ctx.session, ctx.tenant_id)
    return await list_accounts(ctx)


@router.post("/transactions", response_model=schemas.TransactionOut, status_code=201)
async def post_transaction(ctx: WriteCtx, body: schemas.TransactionCreate):
    """Post an atomic, balanced financial transaction."""
    tx = await FinancialService.post_transaction(
        ctx.session,
        ctx.tenant_id,
        reference_type=body.reference_type,
        reference_id=body.reference_id,
        currency=body.currency,
        entries=body.entries,
        decision_id=body.decision_id,
        effect_id=body.effect_id,
        description=body.description,
    )
    # Reload with entries and accounts
    loaded = await ctx.session.scalar(
        select(FinancialTransaction)
        .where(
            FinancialTransaction.tenant_id == ctx.tenant_id,
            FinancialTransaction.transaction_id == tx.transaction_id,
        )
        .options(selectinload(FinancialTransaction.entries).selectinload(FinancialEntry.account))
    )
    return _tx_dict(loaded or tx)


@router.get("/transactions", response_model=schemas.TransactionListOut)
async def list_transactions(
    ctx: TenantCtxDep,
    reference_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """List financial transactions with entries."""
    conditions = [FinancialTransaction.tenant_id == ctx.tenant_id]
    if reference_type:
        conditions.append(FinancialTransaction.reference_type == reference_type)

    total = (
        await ctx.session.execute(
            select(func.count(FinancialTransaction.transaction_id)).where(*conditions)
        )
    ).scalar_one()

    rows = (
        await ctx.session.execute(
            select(FinancialTransaction)
            .where(*conditions)
            .options(selectinload(FinancialTransaction.entries).selectinload(FinancialEntry.account))
            .order_by(FinancialTransaction.posted_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return {
        "items": [_tx_dict(r) for r in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/transactions/{transaction_id}/entries", response_model=list[schemas.EntryOut])
async def list_transaction_entries(
    transaction_id: uuid.UUID,
    ctx: TenantCtxDep,
):
    """List debits and credits for a specific transaction."""
    rows = (
        await ctx.session.execute(
            select(FinancialEntry)
            .where(
                FinancialEntry.tenant_id == ctx.tenant_id,
                FinancialEntry.transaction_id == transaction_id,
            )
            .options(selectinload(FinancialEntry.account))
            .order_by(FinancialEntry.entry_type.asc())
        )
    ).scalars().all()
    return [
        schemas.EntryOut(
            entry_id=e.entry_id,
            account_id=e.account_id,
            account_code=e.account.code if e.account else None,
            entry_type=e.entry_type,
            amount=e.amount,
            memo=e.memo,
        )
        for e in rows
    ]


@router.get("/trial-balance", response_model=schemas.TrialBalanceOut)
async def get_trial_balance(ctx: TenantCtxDep):
    """Retrieve full trial balance proving ledger debits equal credits."""
    return await FinancialService.get_trial_balance(ctx.session, ctx.tenant_id)

