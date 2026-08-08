"""Schemas for the customer portal — the first surface outside the company.

Kept in their own module and never sharing a class with the internal API. Reuse is
how a field leaks: an internal schema gains `unit_cost` one day for a staff screen,
and it appears in a customer's response the same afternoon with nobody noticing.
Every portal response is written out explicitly here, field by field.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PortalLoginIn(BaseModel):
    login_id: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class PortalCustomerOut(BaseModel):
    """Who the portal thinks you are.

    No credit limit, no price tier, no salesman — none of it is the customer's
    business and all of it says something about how we treat them commercially.
    """

    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    name: str
    phone: str | None
    address: str | None
    must_change_password: bool


class PortalTokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    customer: PortalCustomerOut


class PortalRefreshIn(BaseModel):
    refresh_token: str


class PortalPasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


# --- Office side: managing who can get in ---
class CustomerLoginCreateIn(BaseModel):
    customer_id: int
    login_id: str = Field(min_length=3, max_length=120)
    # The office reads this out to the customer. There is no mail or SMS gateway
    # configured, so a self-service invite link would silently never arrive.
    temporary_password: str = Field(min_length=8, max_length=200)


class CustomerLoginOut(BaseModel):
    """What staff see about a portal account. Never the hash, not even truncated."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    login_id: str
    is_active: bool
    must_change_password: bool
    is_locked: bool = False
    last_login_at: datetime | None
    created_at: datetime


class CustomerLoginUpdateIn(BaseModel):
    is_active: bool | None = None
    # Setting a new temporary password also clears any lockout and forces a change
    # at next sign-in — the whole point of the office resetting it.
    temporary_password: str | None = Field(default=None, min_length=8, max_length=200)
