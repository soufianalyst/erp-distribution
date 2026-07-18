"""Aggregate router for API v1 — each module registers its sub-router here."""

from fastapi import APIRouter

from app.api.v1 import (
    accounting,
    analytics,
    auth,
    cashier,
    delivery,
    expenses,
    inventory,
    purchases,
    sales,
    settings,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(inventory.router)
api_router.include_router(purchases.router)
api_router.include_router(sales.router)
api_router.include_router(cashier.router)
api_router.include_router(expenses.router)
api_router.include_router(accounting.router)
api_router.include_router(delivery.router)
api_router.include_router(analytics.router)
api_router.include_router(settings.router)
