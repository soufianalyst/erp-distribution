"""Import all models here so Base.metadata knows every table (needed by create_all/Alembic)."""

from app.domain.models.accounting import Account, AccountType, JournalEntry, JournalItem
from app.domain.models.delivery import (
    DeliveryStop,
    DeliveryTrip,
    StopStatus,
    TripStatus,
)
from app.domain.models.inventory import Product, ProductBatch, ProductUnit, Warehouse
from app.domain.models.purchases import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchasePaymentMethod,
    Supplier,
    SupplierPayment,
)
from app.domain.models.sales import (
    Customer,
    FulfillmentType,
    CustomerPayment,
    PriceTier,
    ReturnReason,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPaymentMethod,
    SalesReturn,
    SalesReturnLine,
)
from app.domain.models.user import User, UserRole

__all__ = [
    "Account",
    "AccountType",
    "Customer",
    "FulfillmentType",
    "DeliveryStop",
    "DeliveryTrip",
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
    "PurchasePaymentMethod",
    "ReturnReason",
    "SalesInvoice",
    "SalesInvoiceLine",
    "SalesPaymentMethod",
    "SalesReturn",
    "SalesReturnLine",
    "Supplier",
    "SupplierPayment",
    "User",
    "UserRole",
    "Warehouse",
]
