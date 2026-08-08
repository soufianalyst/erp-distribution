"""Accounting entities: chart of accounts and double-entry journal."""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AccountType(str, enum.Enum):
    ASSET = "asset"  # أصول
    LIABILITY = "liability"  # التزامات
    EQUITY = "equity"  # حقوق ملكية
    REVENUE = "revenue"  # إيرادات
    EXPENSE = "expense"  # مصاريف


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # System accounts are seeded and used by automatic postings; they cannot be removed.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JournalEntry(Base):
    """A balanced double-entry document; items always sum debit == credit."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    # Source document that generated this entry (e.g. sales_invoice #12); manual when None.
    reference_type: Mapped[str | None] = mapped_column(String(30), index=True)
    reference_id: Mapped[int | None] = mapped_column(index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list["JournalItem"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class JournalItem(Base):
    __tablename__ = "journal_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    debit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    credit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )

    entry: Mapped[JournalEntry] = relationship(back_populates="items")
    account: Mapped[Account] = relationship()


class BankStatementLine(Base):
    """One line from the bank's own statement, entered manually and matched
    against an existing journal item posted to the bank account (1015)."""

    __tablename__ = "bank_statement_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    line_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # "in"/"out"
    matched_journal_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_items.id"), unique=True, nullable=True
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    matched_journal_item: Mapped["JournalItem | None"] = relationship()
