#!/bin/sh
# Migrate, then serve. Two things depend on this order:
#
#   * AUTO_CREATE_TABLES is False in production, so nothing else creates the schema.
#   * `set -e` means a failed migration stops the deploy instead of starting a server
#     against a half-migrated database, which is the failure that looks fine until an
#     insert hits a column that was never added.
#
# The port comes from Render, which injects $PORT and expects the process to honour it.
set -e

echo "Running database migrations..."
alembic upgrade head

PORT=${PORT:-10000}
echo "Starting server on port $PORT..."
exec uvicorn main:app --host 0.0.0.0 --port $PORT
