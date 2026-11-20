"""Request bodies (validated by FastAPI/Pydantic; errors become HTTP 422)."""
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from common.db import IBAN_PATTERN, REGIONS

from . import validation


class _PersonFields(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    email: str
    phone: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        if not validation.is_valid_email(v):
            raise ValueError("email inválido")
        return v.lower()

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        if not validation.is_valid_phone(v):
            raise ValueError("telefone inválido (9 a 15 dígitos, opcionalmente com +)")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if problems := validation.password_problems(v):
            raise ValueError("senha fraca: precisa de " + ", ".join(problems))
        return v


class RegisterRequest(_PersonFields):
    region: Literal[REGIONS]
    document_id: str = Field(min_length=5, max_length=40)
    birth_date: date


class StaffRequest(_PersonFields):
    role: Literal["operador", "auditor", "admin"]
    region: Literal[REGIONS] = "EU"


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ApproveKycRequest(BaseModel):
    currency: Literal["EUR", "USD", "MZN"] | None = None  # default: currency of the region


# --- administração de utilizadores e beneficiários ---------------------------------

class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=3, max_length=120)
    email: str | None = None
    phone: str | None = None
    role: Literal["operador", "auditor", "admin"] | None = None

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if v is not None and not validation.is_valid_email(v):
            raise ValueError("email inválido")
        return v.lower() if v else v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v):
        if v is not None and not validation.is_valid_phone(v):
            raise ValueError("telefone inválido")
        return v


class StatusChange(BaseModel):
    action: Literal["block", "unblock", "deactivate", "reactivate"]
    reason: str | None = Field(default=None, max_length=200)




class BeneficiaryIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    iban: str = Field(pattern=IBAN_PATTERN)
    nickname: str | None = Field(default=None, max_length=60)
    favorite: bool = False


class BeneficiaryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    nickname: str | None = Field(default=None, max_length=60)
    favorite: bool | None = None


class AdminBeneficiaryIn(BeneficiaryIn):
    owner_id: uuid.UUID
