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
    # The company's own registration numbers, printed in the header of documents that
    # an authority reads: NIF (رقم التعريف الضريبي) and NIS (رقم التعريف الإحصائي).
    # `tax_number` is the NIF and predates the name — renaming a column that eight
    # print pages and the settings screen already read would be churn for a label.
    tax_number: Mapped[str | None] = mapped_column(String(50))
    statistical_number: Mapped[str | None] = mapped_column(String(50))
    # The country the business operates in — decides which country-specific tax
    # rates are offered when invoicing.
    country_code: Mapped[str | None] = mapped_column(String(2))
    # IANA name (e.g. "Asia/Qatar"). The company's own midnight is where a business
    # day starts and ends — the cashier's closing report, and anything else asked for
    # "by day". Deliberately not the server's timezone: a cloud host in UTC must not
    # be able to move the day a till is balanced on.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
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

    # --- Replenishment ---
    # How long a supplier typically takes between an order and the goods arriving.
    # Stated rather than measured: this system has no purchase-order history to
    # learn from, and a lead time guessed from nothing would be worse than one a
    # buyer typed knowing their own suppliers. Overridable per supplier.
    default_lead_time_days: Mapped[int] = mapped_column(
        nullable=False, default=7, server_default="7"
    )
    # Extra days of cover carried against demand that arrives faster than usual.
    # Expressed in days rather than as a statistical service level because a
    # warehouse manager can argue with "one week of stock" and cannot argue with
    # z=1.65 — and because with demand this intermittent, a normal-curve safety
    # stock would be false precision.
    safety_stock_days: Mapped[int] = mapped_column(
        nullable=False, default=7, server_default="7"
    )
    # How often purchasing actually places orders. An order must cover demand until
    # the next one is placed, not merely until this one lands.
    reorder_review_days: Mapped[int] = mapped_column(
        nullable=False, default=14, server_default="14"
    )

    # --- Clearance ---
    # The deepest markdown the engine may ever propose. A ceiling rather than a
    # target: past it, pricing is not clearing the stock, it is giving it away and
    # teaching customers to wait for the fire sale. It lives here, not as a query
    # parameter, because it is company policy — the screen may choose to be gentler
    # on a given day, never harsher.
    markdown_max_discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("50"), server_default="50"
    )

    # --- Credit control ---
    # Refuse a new credit sale when the customer holds a debt older than this many
    # days. Zero disables it, which is the default: switching it on stops sales, and
    # that is a commercial decision for the owner rather than a shipped assumption.
    #
    # This is the control the credit limit cannot be. A limit measures how *much* is
    # owed; it has nothing to say about how long it has been owed, so a customer
    # sitting a year overdue but well under their ceiling passes the check every
    # time — which is exactly the state the seeded book of business is in.
    credit_block_after_days: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )

    @property
    def country_name(self) -> str | None:
        """Arabic country name resolved from the stored code."""
        return country_name(self.country_code)
