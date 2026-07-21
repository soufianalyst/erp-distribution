#!/bin/sh
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Seeding default data..."
SEED_ON_STARTUP=true python -c "
import asyncio
import os
os.environ['SEED_ON_STARTUP'] = 'true'
from app.db.session import AsyncSessionLocal
from app.services.accounting.accounting_service import seed_chart_of_accounts
from app.services.expenses.expense_service import seed_expense_accounts

async def seed():
    async with AsyncSessionLocal() as session:
        await seed_chart_of_accounts(session)
        await seed_expense_accounts(session)

asyncio.run(seed())
print('Seeding complete.')
"

echo "Starting server..."
PORT=${PORT:-10000}
exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2
