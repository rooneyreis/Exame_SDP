"""Request bodies. Money is always Decimal with 2 decimal places (never float)."""
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from common.db import IBAN_PATTERN, REGIONS

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]


class CashOperation(BaseModel):
    amount: Money
    description: str | None = Field(default=None, max_length=140)


class TransferRequest(BaseModel):
    from_iban: str
    to_iban: str
    # O máximo é configurável pelo administrador (tabela settings): validado no endpoint e no coordenador.
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("1000000.00"), max_digits=18, decimal_places=2)]


class ChaosRequest(BaseModel):
    pause_before_prepare: int | None = Field(default=None, ge=0, le=120)
    pause_after_prepare: int | None = Field(default=None, ge=0, le=120)
    crash_after_prepare: bool | None = None
    crash_after_decision: bool | None = None
    fail_participant: Literal[(*REGIONS, "")] | None = None
    off: bool | None = None


class CreateAccountRequest(BaseModel):
    user_id: uuid.UUID
    region: Literal[REGIONS]
    currency: Literal["EUR", "USD", "MZN"]


class TransferRequestIn(BaseModel):
    """Transferência registada por um operador em nome de um cliente."""
    from_iban: str = Field(pattern=IBAN_PATTERN)
    to_iban: str = Field(pattern=IBAN_PATTERN)
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("1000000.00"), max_digits=18, decimal_places=2)]
    beneficiary_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=140)


class Decision(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class AccountUpdate(BaseModel):
    daily_limit: Annotated[Decimal, Field(gt=0, le=Decimal("10000000.00"), max_digits=18, decimal_places=2)] | None = None
    status: Literal["ATIVA", "BLOQUEADA"] | None = None


class SettingsUpdate(BaseModel):
    # valores em EUR
    max_transfer_amount: Annotated[Decimal, Field(gt=0, le=Decimal("1000000.00"), decimal_places=2)] | None = None
    approval_threshold: Annotated[Decimal, Field(gt=0, le=Decimal("1000000.00"), decimal_places=2)] | None = None
    daily_limit_eur: Annotated[Decimal, Field(gt=0, le=Decimal("10000000.00"), decimal_places=2)] | None = None
    max_accounts_per_client: Annotated[int, Field(ge=1, le=20)] | None = None


CURRENCIES = ("EUR", "USD", "MZN")


class AccountRequestIn(BaseModel):
    """Pedido de uma conta adicional: o cliente escolhe a região (shard) e a moeda."""
    region: Literal[REGIONS]
    currency: Literal[CURRENCIES]


class DirectAccountIn(AccountRequestIn):
    """Abertura direta ao balcão (operador)."""
    user_id: uuid.UUID
