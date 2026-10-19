#!/usr/bin/env bash
set -e

cd /app/backend

echo "==> Running database migrations with Alembic..."
alembic upgrade head

# Auto-create admin user on deployment if ADMIN_EMAIL & ADMIN_PASSWORD env vars are set
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "==> Setting up admin user ($ADMIN_EMAIL)..."
    python -m app.cli create-admin \
        --email "$ADMIN_EMAIL" \
        --password "$ADMIN_PASSWORD" \
        --name "${ADMIN_NAME:-Administrator}" || true
fi

echo "==> Starting BeforeYouGo application on port ${PORT:-8001}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8001}"
