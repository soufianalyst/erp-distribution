"""Cashier domain: individual cash/card movement events at the register.

The cashier's till has two directions: money IN (collecting a pending sales
invoice) and money OUT (paying a pending purchase invoice or expense). Each
movement references the document it settles via reference_type/reference_id,
mirroring the same pattern JournalEntry already uses — this is what lets the
daily summary reconcile net cash across all three document types.

An invoice/expense may be settled in installments (partial payments); one row
here per collection/disbursement is what lets a cashier reconcile exactly what
they personally handled on a given day.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CashMovement(Base):
    __tablename__ = "cash_movements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # "in" (collecting a sales invoice) or "out" (paying a purchase invoice/expense).
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    # "sales_invoice" | "purchase_invoice" | "expense".
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[int] = mapped_column(nullable=False)
    # The customer/supplier this movement is with, when there is one (an
    # expense typically has no tracked party).
    party_id: Mapped[int | None] = mapped_column(nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    collected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
