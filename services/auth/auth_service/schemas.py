"""Request bodies (validated by FastAPI/Pydantic; errors become HTTP 422)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    region: Literal["EU", "AM"]
    document_id: str = Field(min_length=5, max_length=40)
    birth_date: date


class StaffRequest(_PersonFields):
    role: Literal["operador", "auditor", "admin"]
    region: Literal["EU", "AM"] = "EU"


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ApproveKycRequest(BaseModel):
    currency: Literal["EUR", "USD", "MZN"] | None = None  # default: currency of the region
