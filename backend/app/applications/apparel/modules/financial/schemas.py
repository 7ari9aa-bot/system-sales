"""Schemas for the Financial module (V12 Wave C §31)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

PAGE_LIMIT_DEFAULT = 50
PAGE_LIMIT_MAX = 200


class AccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    account_type: str = Field(pattern="^(ASSET|LIABILITY|EQUITY|REVENUE|EXPENSE)$")
    currency: str = Field(default="SAR", min_length=3, max_length=3)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    account_type: str
    currency: str
    is_active: bool
    created_at: datetime


class AccountListOut(BaseModel):
    items: list[AccountOut]
    total: int


class EntryCreate(BaseModel):
    account_id: uuid.UUID | None = None
    account_code: str | None = Field(default=None, max_length=32)
    entry_type: str = Field(pattern="^(DEBIT|CREDIT)$")
    amount: Decimal = Field(gt=Decimal("0.0000"), max_digits=14, decimal_places=4)
    memo: str | None = Field(default=None, max_length=255)


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_id: uuid.UUID
    account_id: uuid.UUID
    account_code: str | None = None
    entry_type: str
    amount: Decimal
    memo: str | None = None


class TransactionCreate(BaseModel):
    reference_type: str = Field(min_length=1, max_length=64)
    reference_id: uuid.UUID | None = None
    decision_id: uuid.UUID | None = None
    effect_id: uuid.UUID | None = None
    currency: str = Field(default="SAR", min_length=3, max_length=3)
    description: str | None = None
    entries: list[EntryCreate] = Field(min_length=2)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: uuid.UUID
    tenant_id: uuid.UUID
    reference_type: str
    reference_id: uuid.UUID | None = None
    decision_id: uuid.UUID | None = None
    effect_id: uuid.UUID | None = None
    currency: str
    status: str
    description: str | None = None
    posted_at: datetime
    entries: list[EntryOut]
    total_debits: Decimal
    total_credits: Decimal


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class TrialBalanceItem(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    account_type: str
    total_debit: Decimal
    total_credit: Decimal
    net_balance: Decimal


class TrialBalanceOut(BaseModel):
    tenant_id: uuid.UUID
    currency: str
    generated_at: datetime
    items: list[TrialBalanceItem]
    total_debits: Decimal
    total_credits: Decimal
    is_balanced: bool
