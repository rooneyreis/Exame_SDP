"""Request bodies. Money is always Decimal with 2 decimal places (never float)."""
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]


class CashOperation(BaseModel):
    amount: Money
    description: str | None = Field(default=None, max_length=140)


class CreateAccountRequest(BaseModel):
    user_id: uuid.UUID
    region: Literal["EU", "AM"]
    currency: Literal["EUR", "USD", "MZN"]
