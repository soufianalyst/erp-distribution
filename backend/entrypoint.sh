#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

PORT=${PORT:-10000}
echo "Starting server on port $PORT..."
exec uvicorn main:app --host 0.0.0.0 --port $PORT
