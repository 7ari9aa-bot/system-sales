#!/bin/bash
# Mirrors .github/workflows/ci.yml env exactly, against the local Docker
# Postgres (5433) + Redis (6379) spun up for the agent-layer verification.
cd "C:/Users/CS/agent-fixes/backend" || exit 1
export ENVIRONMENT=local
export DATABASE_URL_ADMIN="postgresql+asyncpg://postgres:postgres@localhost:5433/sales"
export SALES_APP_DB_PASSWORD=ci-app-password
export DATABASE_URL_APP="postgresql+asyncpg://sales_app:ci-app-password@localhost:5433/sales"
export DATABASE_URL_APP_ADMIN="postgresql+asyncpg://sales_app:ci-app-password@localhost:5433/sales"
export DATABASE_URL="postgresql+asyncpg://sales_app:ci-app-password@localhost:5433/sales"
exec ./.venv/Scripts/python.exe -m pytest "$@"
