"""Import all models here so Base.metadata knows every table (needed by create_all/Alembic)."""

from app.domain.models.accounting import Account, AccountType, JournalEntry, JournalItem
from app.domain.models.cashier import CashMovement
from app.domain.models.delivery import (
    DeliveryStop,
    DeliveryTrip,
    StopStatus,
    TripStatus,
)
from app.domain.models.expenses import Expense, ExpenseCategory, ExpensePaymentMethod
from app.domain.models.inventory import Product, ProductBatch, ProductUnit, Warehouse
from app.domain.models.purchases import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseInvoiceTax,
    PurchasePaymentMethod,
    Supplier,
    SupplierPayment,
)
from app.domain.models.settings import CompanySettings, TaxRate
from app.domain.models.sales import (
    Customer,
    FulfillmentType,
    CustomerPayment,
    PriceTier,
    ReturnReason,
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceTax,
    SalesPaymentMethod,
    SalesReturn,
    SalesReturnLine,
)
from app.domain.models.user import User, UserRole

__all__ = [
    "Account",
    "AccountType",
    "CashMovement",
    "CompanySettings",
    "Customer",
    "FulfillmentType",
    "DeliveryStop",
    "DeliveryTrip",
    "Expense",
    "ExpenseCategory",
    "ExpensePaymentMethod",
    "StopStatus",
    "TripStatus",
    "JournalEntry",
    "JournalItem",
    "CustomerPayment",
    "PriceTier",
    "Product",
    "ProductBatch",
    "ProductUnit",
    "PurchaseInvoice",
    "PurchaseInvoiceLine",
    "PurchaseInvoiceTax",
    "PurchasePaymentMethod",
    "ReturnReason",
    "SalesInvoice",
    "SalesInvoiceLine",
    "SalesInvoiceTax",
    "SalesPaymentMethod",
    "SalesReturn",
    "SalesReturnLine",
    "Supplier",
    "SupplierPayment",
    "TaxRate",
    "User",
    "UserRole",
    "Warehouse",
]
