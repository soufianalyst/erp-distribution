"""System-wide configuration: tax rates and company identity for print headers.

Business rule: taxes are never hardcoded to VAT — an admin can define any
number of tax types (VAT, GST, Sales Tax, custom), each with its own rate and
optionally scoped to a country, enabled/disabled independently. Sales invoices
may apply any number of them at once (see SalesInvoiceTax).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.countries import country_name
from app.db.base import Base


class TaxRate(Base):
    __tablename__ = "tax_rates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Short unique identifier, e.g. "VAT", "GST", "SALES_TAX".
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    # Percentage value (e.g. 16.000 means 16%), never a raw fraction.
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    # Which country this tax belongs to (ISO 3166-1 alpha-2, see core/countries).
    # NULL means it applies everywhere; a code means it is only offered for
    # invoicing when it matches the company's own country.
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # At most one tax rate may be the default pre-selected on new invoices.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def country_name(self) -> str | None:
        """Display label resolved from the code; None when it applies everywhere."""
        return country_name(self.country_code)


class CompanySettings(Base):
    """Singleton row (always id=1) — company identity shown on printed documents."""

    __tablename__ = "company_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    tagline: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(30))
    tax_number: Mapped[str | None] = mapped_column(String(50))
    # The country the business operates in — decides which country-specific tax
    # rates are offered when invoicing.
    country_code: Mapped[str | None] = mapped_column(String(2))
    currency_code: Mapped[str] = mapped_column(
        String(10), nullable=False, default="SAR"
    )
    currency_symbol: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ر.س"
    )
    # Value of stock difference a salesman's round may be settled with before a
    # supervisor's approval is required. Configurable because "negligible" is a
    # business judgement: what a grocery shrugs at, a wholesaler investigates.
    # Zero means every non-zero difference needs approval.
    round_variance_approval_limit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("50.00"), server_default="50.00"
    )

    @property
    def country_name(self) -> str | None:
        """Arabic country name resolved from the stored code."""
        return country_name(self.country_code)
