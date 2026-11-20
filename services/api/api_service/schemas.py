"""Request bodies. Money is always Decimal with 2 decimal places (never float)."""
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]


class CashOperation(BaseModel):
    amount: Money
    description: str | None = Field(default=None, max_length=140)


class TransferRequest(BaseModel):
    from_iban: str
    to_iban: str
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("10000.00"), max_digits=18, decimal_places=2)]


class ChaosRequest(BaseModel):
    pause_before_prepare: int | None = Field(default=None, ge=0, le=120)
    pause_after_prepare: int | None = Field(default=None, ge=0, le=120)
    crash_after_prepare: bool | None = None
    crash_after_decision: bool | None = None
    fail_participant: Literal["EU", "AM", ""] | None = None
    off: bool | None = None


class CreateAccountRequest(BaseModel):
    user_id: uuid.UUID
    region: Literal["EU", "AM"]
    currency: Literal["EUR", "USD", "MZN"]
