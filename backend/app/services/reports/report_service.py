"""Reporting service: dashboard KPIs, damage reports, analytics, tax reports, income statement, and balance sheet."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.accounting import Account, AccountType, JournalEntry, JournalItem
from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import (
    Customer,
    InvoiceTaxLine,
    ReturnReason,
    ReturnTaxLine,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
    SalesPaymentMethod,
    TaxType,
)
from app.domain.models.purchases import PurchaseInvoice
from app.domain.models.user import User
from app.services.accounting.accounting_service import (
    COGS,
    DAMAGE_LOSS,
    SALES_REVENUE,
    SALES_RETURNS,
)


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dashboard_kpis(self) -> dict:
        """Aggregate KPIs for the analytical dashboard."""
        today = date.today()
        month_start = today.replace(day=1)
        prev_month_end = month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        # Current month sales
        sales_this_month = await self.session.execute(
            select(
                func.coalesce(func.count(SalesInvoice.id), 0),
                func.coalesce(func.sum(SalesInvoice.total), 0),
                func.coalesce(func.sum(SalesInvoice.paid_amount), 0),
            ).where(SalesInvoice.invoice_date >= month_start)
        )
        sales_count, sales_revenue, sales_collected = sales_this_month.one()

        # Previous month sales (for comparison)
        sales_prev_month = await self.session.execute(
            select(
                func.coalesce(func.count(SalesInvoice.id), 0),
                func.coalesce(func.sum(SalesInvoice.total), 0),
            ).where(
                SalesInvoice.invoice_date >= prev_month_start,
                SalesInvoice.invoice_date <= prev_month_end,
            )
        )
        prev_sales_count, prev_sales_revenue = sales_prev_month.one()

        # Current month purchases
        purchases_this_month = await self.session.execute(
            select(
                func.coalesce(func.count(PurchaseInvoice.id), 0),
                func.coalesce(func.sum(PurchaseInvoice.total), 0),
            ).where(PurchaseInvoice.invoice_date >= month_start)
        )
        purchase_count, purchase_total = purchases_this_month.one()

        # Returns this month
        returns_this_month = await self.session.execute(
            select(
                func.coalesce(func.count(SalesReturn.id), 0),
                func.coalesce(func.sum(SalesReturn.total), 0),
            ).where(SalesReturn.created_at >= month_start)
        )
        returns_count, returns_total = returns_this_month.one()

        # Outstanding customer balance
        customer_balance = await self.session.execute(
            select(func.coalesce(func.sum(SalesInvoice.total - SalesInvoice.paid_amount), 0))
            .where(
                SalesInvoice.payment_method == SalesPaymentMethod.CREDIT,
                SalesInvoice.total > SalesInvoice.paid_amount,
            )
        )
        outstanding_receivables = customer_balance.scalar_one()

        # Low stock products
        low_stock = await self.session.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.is_active == True, Product.min_stock_level > 0)  # noqa: E712
        )
        total_active_products = await self.session.execute(
            select(func.count()).select_from(Product).where(Product.is_active == True)  # noqa: E712
        )

        # Count products below min stock
        from sqlalchemy.orm import selectinload
        products_result = await self.session.execute(
            select(Product).options(selectinload(Product.units)).where(Product.is_active == True)  # noqa: E712
        )
        all_products = products_result.scalars().all()

        low_stock_count = 0
        for product in all_products:
            if product.min_stock_level > 0:
                stock_result = await self.session.execute(
                    select(func.coalesce(func.sum(ProductBatch.quantity), 0)).where(
                        ProductBatch.product_id == product.id,
                        ProductBatch.quantity > 0,
                    )
                )
                total_qty = stock_result.scalar_one()
                if Decimal(str(total_qty)) < product.min_stock_level:
                    low_stock_count += 1

        return {
            "sales_this_month": {
                "count": int(sales_count),
                "revenue": Decimal(str(sales_revenue)),
                "collected": Decimal(str(sales_collected)),
                "prev_count": int(prev_sales_count),
                "prev_revenue": Decimal(str(prev_sales_revenue)),
            },
            "purchases_this_month": {
                "count": int(purchase_count),
                "total": Decimal(str(purchase_total)),
            },
            "returns_this_month": {
                "count": int(returns_count),
                "total": Decimal(str(returns_total)),
            },
            "outstanding_receivables": Decimal(str(outstanding_receivables)),
            "low_stock_count": low_stock_count,
            "total_products": total_active_products.scalar_one(),
        }

    async def top_products(self, limit: int = 5) -> list[dict]:
        """Top selling products this month by quantity."""
        month_start = date.today().replace(day=1)
        result = await self.session.execute(
            select(
                Product.id,
                Product.name,
                Product.sku,
                Product.base_unit_name,
                func.coalesce(func.sum(SalesInvoiceLine.quantity), 0).label("total_qty"),
                func.coalesce(func.sum(SalesInvoiceLine.line_total), 0).label("total_revenue"),
            )
            .join(SalesInvoiceLine, SalesInvoiceLine.product_id == Product.id)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(SalesInvoice.invoice_date >= month_start)
            .group_by(Product.id, Product.name, Product.sku, Product.base_unit_name)
            .order_by(func.sum(SalesInvoiceLine.quantity).desc())
            .limit(limit)
        )
        return [
            {
                "product_id": row[0],
                "product_name": row[1],
                "sku": row[2],
                "base_unit_name": row[3],
                "total_quantity": Decimal(str(row[4])),
                "total_revenue": Decimal(str(row[5])),
            }
            for row in result.all()
        ]

    async def salesman_performance(self) -> list[dict]:
        """Sales performance per salesman this month."""
        month_start = date.today().replace(day=1)
        result = await self.session.execute(
            select(
                User.id,
                User.full_name,
                func.coalesce(func.count(SalesInvoice.id), 0).label("invoice_count"),
                func.coalesce(func.sum(SalesInvoice.total), 0).label("total_revenue"),
                func.coalesce(func.sum(SalesInvoice.paid_amount), 0).label("collected"),
            )
            .join(SalesInvoice, SalesInvoice.salesman_id == User.id)
            .where(SalesInvoice.invoice_date >= month_start, User.role == "sales")
            .group_by(User.id, User.full_name)
            .order_by(func.sum(SalesInvoice.total).desc())
        )
        return [
            {
                "salesman_id": row[0],
                "salesman_name": row[1],
                "invoice_count": int(row[2]),
                "total_revenue": Decimal(str(row[3])),
                "collected": Decimal(str(row[4])),
            }
            for row in result.all()
        ]

    async def damage_report(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Aggregated damage/return data grouped by product and reason."""
        stmt = (
            select(
                Product.id,
                Product.name,
                Product.sku,
                SalesReturnLine.batch_id,
                SalesReturnLine.quantity,
                SalesReturnLine.unit_price,
                SalesReturnLine.line_total,
                SalesReturn.reason,
                SalesReturn.created_at,
            )
            .join(SalesReturn, SalesReturn.id == SalesReturnLine.return_id)
            .join(Product, Product.id == SalesReturnLine.product_id)
            .where(SalesReturn.reason.in_(["damaged_customer", "damaged_transport"]))
        )
        if date_from is not None:
            stmt = stmt.where(SalesReturn.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(SalesReturn.created_at <= date_to)
        stmt = stmt.order_by(Product.name, SalesReturn.created_at)

        result = await self.session.execute(stmt)
        return [
            {
                "product_id": row[0],
                "product_name": row[1],
                "sku": row[2],
                "batch_id": row[3],
                "quantity": Decimal(str(row[4])),
                "unit_price": Decimal(str(row[5])),
                "line_total": Decimal(str(row[6])),
                "reason": row[7],
                "created_at": row[8],
            }
            for row in result.all()
        ]

    async def tax_report(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """Tax collected on sales, returned via sales returns, and paid on purchases.

        Returns a summary plus per-tax-type breakdown.
        """
        # --- Tax collected on sales (grouped by tax type) ---
        sales_tax_stmt = (
            select(
                TaxType.id,
                TaxType.name,
                TaxType.rate,
                TaxType.accounting_code,
                func.coalesce(func.sum(InvoiceTaxLine.amount), 0).label("collected"),
                func.coalesce(func.sum(InvoiceTaxLine.amount * InvoiceTaxLine.rate_at_time / func.nullif(InvoiceTaxLine.amount, 0) * 0), 0).label("_dummy"),
            )
            .join(InvoiceTaxLine, InvoiceTaxLine.tax_type_id == TaxType.id)
            .join(SalesInvoice, SalesInvoice.id == InvoiceTaxLine.invoice_id)
            .group_by(TaxType.id, TaxType.name, TaxType.rate, TaxType.accounting_code)
            .order_by(TaxType.id)
        )
        if date_from is not None:
            sales_tax_stmt = sales_tax_stmt.where(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            sales_tax_stmt = sales_tax_stmt.where(SalesInvoice.invoice_date <= date_to)
        sales_tax_result = await self.session.execute(sales_tax_stmt)

        collected_by_type: dict[int, dict] = {}
        for row in sales_tax_result.all():
            collected_by_type[row[0]] = {
                "tax_type_id": row[0],
                "tax_type_name": row[1],
                "rate": Decimal(str(row[2])),
                "accounting_code": row[3],
                "collected": Decimal(str(row[4])),
                "returned": Decimal("0"),
                "net_collected": Decimal(str(row[4])),
            }

        # --- Tax returned via sales returns (grouped by tax type) ---
        returns_tax_stmt = (
            select(
                ReturnTaxLine.tax_type_id,
                func.coalesce(func.sum(ReturnTaxLine.amount), 0).label("returned"),
            )
            .join(SalesReturn, SalesReturn.id == ReturnTaxLine.return_id)
            .group_by(ReturnTaxLine.tax_type_id)
        )
        if date_from is not None:
            returns_tax_stmt = returns_tax_stmt.where(SalesReturn.created_at >= date_from)
        if date_to is not None:
            returns_tax_stmt = returns_tax_stmt.where(SalesReturn.created_at <= date_to)
        returns_result = await self.session.execute(returns_tax_stmt)
        for row in returns_result.all():
            ttid = row[0]
            ret_amt = Decimal(str(row[1]))
            if ttid in collected_by_type:
                collected_by_type[ttid]["returned"] = ret_amt
                collected_by_type[ttid]["net_collected"] = (
                    collected_by_type[ttid]["collected"] - ret_amt
                )

        # Ensure all tax types appear even if zero in period.
        all_taxes = await self.session.execute(select(TaxType).order_by(TaxType.id))
        for tt in all_taxes.scalars().all():
            if tt.id not in collected_by_type:
                collected_by_type[tt.id] = {
                    "tax_type_id": tt.id,
                    "tax_type_name": tt.name,
                    "rate": tt.rate,
                    "accounting_code": tt.accounting_code,
                    "collected": Decimal("0"),
                    "returned": Decimal("0"),
                    "net_collected": Decimal("0"),
                }

        # --- Tax paid on purchases (single total, no per-type breakdown) ---
        purchase_tax_stmt = select(
            func.coalesce(func.sum(PurchaseInvoice.vat_amount), 0)
        )
        if date_from is not None:
            purchase_tax_stmt = purchase_tax_stmt.where(
                PurchaseInvoice.invoice_date >= date_from
            )
        if date_to is not None:
            purchase_tax_stmt = purchase_tax_stmt.where(
                PurchaseInvoice.invoice_date <= date_to
            )
        total_purchase_vat = Decimal(str((await self.session.execute(purchase_tax_stmt)).scalar_one()))

        by_type = list(collected_by_type.values())
        total_collected = sum((t["collected"] for t in by_type), Decimal("0"))
        total_returned = sum((t["returned"] for t in by_type), Decimal("0"))
        net_collected = total_collected - total_returned

        return {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "total_collected": total_collected,
            "total_returned": total_returned,
            "net_collected": net_collected,
            "total_paid_on_purchases": total_purchase_vat,
            "net_tax_payable": net_collected - total_purchase_vat,
            "by_tax_type": by_type,
        }

    async def income_statement(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> dict:
        """Income statement (P&L): revenue minus COGS minus expenses = net profit."""
        # Aggregate journal item balances by account code in the period.
        stmt = (
            select(
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(func.sum(JournalItem.debit - JournalItem.credit), 0),
            )
            .join(Account, Account.id == JournalItem.account_id)
            .join(JournalEntry, JournalEntry.id == JournalItem.entry_id)
            .group_by(Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )
        if date_from:
            stmt = stmt.where(JournalEntry.entry_date >= date_from)
        if date_to:
            stmt = stmt.where(JournalEntry.entry_date <= date_to)

        result = await self.session.execute(stmt)
        accounts = [(row[0], row[1], row[2], Decimal(str(row[3]))) for row in result.all()]

        # Income = credit side: revenue accounts have credit > debit, so balance is negative.
        # Expense = debit side: expense accounts have debit > credit, so balance is positive.
        # Net profit = Revenue - Expenses (all from journal balances).
        gross_sales = Decimal("0")
        sales_returns_amt = Decimal("0")
        cogs_amt = Decimal("0")
        damage_loss_amt = Decimal("0")
        expenses_lines = []

        for code, name, acct_type, balance in accounts:
            if code == SALES_REVENUE:
                gross_sales = -balance  # Revenue is negative (credit) in journal
            elif code == SALES_RETURNS:
                sales_returns_amt = -balance
            elif code == COGS:
                cogs_amt = balance
            elif code == DAMAGE_LOSS:
                damage_loss_amt = balance
            elif acct_type == AccountType.EXPENSE and code not in (COGS, DAMAGE_LOSS):
                if balance > 0:
                    expenses_lines.append({
                        "account_code": code,
                        "account_name": name,
                        "balance": balance,
                    })

        net_sales = gross_sales - sales_returns_amt
        gross_profit = net_sales - cogs_amt
        total_expenses = sum((e["balance"] for e in expenses_lines), Decimal("0")) + damage_loss_amt
        net_profit = gross_profit - total_expenses

        return {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "gross_sales": gross_sales,
            "sales_returns": sales_returns_amt,
            "net_sales": net_sales,
            "cogs": cogs_amt,
            "gross_profit": gross_profit,
            "expenses": expenses_lines,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
        }

    async def balance_sheet(self, as_of_date: date | None = None) -> dict:
        """Balance sheet: Assets = Liabilities + Equity at a point in time."""
        cutoff = as_of_date or date.today()

        stmt = (
            select(
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(func.sum(JournalItem.debit - JournalItem.credit), 0),
            )
            .join(Account, Account.id == JournalItem.account_id)
            .join(JournalEntry, JournalEntry.id == JournalItem.entry_id)
            .where(JournalEntry.entry_date <= cutoff)
            .group_by(Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )
        result = await self.session.execute(stmt)
        accounts = [(row[0], row[1], row[2], Decimal(str(row[3]))) for row in result.all()]

        assets_items = []
        liabilities_items = []
        equity_items = []
        total_assets = Decimal("0")
        total_liabilities = Decimal("0")
        total_equity = Decimal("0")

        for code, name, acct_type, balance in accounts:
            if acct_type == AccountType.ASSET:
                if balance > 0:
                    assets_items.append({"account_code": code, "account_name": name, "balance": balance})
                total_assets += balance
            elif acct_type == AccountType.LIABILITY:
                # Liabilities: credit side (negative balance)
                amt = -balance
                if amt > 0:
                    liabilities_items.append({"account_code": code, "account_name": name, "balance": amt})
                total_liabilities += amt
            elif acct_type == AccountType.EQUITY:
                amt = -balance
                if amt > 0:
                    equity_items.append({"account_code": code, "account_name": name, "balance": amt})
                total_equity += amt
            elif acct_type == AccountType.REVENUE:
                # Close revenue into equity for BS
                amt = -balance
                if amt > 0:
                    equity_items.append({"account_code": code, "account_name": name, "balance": amt})
                total_equity += amt
            elif acct_type == AccountType.EXPENSE:
                # Close expenses into equity for BS
                if balance > 0:
                    equity_items.append({"account_code": code, "account_name": name, "balance": -balance})
                total_equity -= balance

        total_liabilities_and_equity = total_liabilities + total_equity

        return {
            "as_of_date": cutoff.isoformat(),
            "assets": {"title": "الأصول", "items": assets_items, "total": total_assets},
            "liabilities": {"title": "الخصوم", "items": liabilities_items, "total": total_liabilities},
            "equity": {"title": "حقوق الملكية", "items": equity_items, "total": total_equity},
            "total_liabilities_and_equity": total_liabilities_and_equity,
        }
