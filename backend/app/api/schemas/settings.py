"""Pydantic schemas (DTOs) for the settings module: tax rates and company identity."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# --- Tax rates ---
class TaxRateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=1, max_length=20)
    rate: Decimal = Field(ge=0, le=100, description="نسبة مئوية، مثال: 16 تعني 16%")
    country: str | None = Field(default=None, max_length=100)
    is_active: bool = True
    is_default: bool = False


class TaxRateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    rate: Decimal | None = Field(default=None, ge=0, le=100)
    country: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    is_default: bool | None = None


class TaxRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    rate: Decimal
    country: str | None
    is_active: bool
    is_default: bool


# --- Company settings ---
class CompanySettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    tagline: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=30)
    tax_number: str | None = Field(default=None, max_length=50)
    currency_code: str | None = Field(default=None, max_length=10)
    currency_symbol: str | None = Field(default=None, max_length=10)


class CompanySettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tagline: str | None
    address: str | None
    phone: str | None
    tax_number: str | None
    currency_code: str
    currency_symbol: str
