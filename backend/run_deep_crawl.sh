#!/bin/bash
# Deep page-crawl inspection — one job owns the whole stack:
# backend (8001, docker DB) -> playwright (auto-starts vite preview with the
# proxy env) -> crawl every route -> report written by the spec itself.
set -u
cd "D:/sales system/backend" || exit 1
export ENVIRONMENT=local
export DATABASE_URL_ADMIN="postgresql+asyncpg://postgres:postgres@localhost:5433/sales"
export SALES_APP_DB_PASSWORD=ci-app-password
export DATABASE_URL_APP="postgresql+asyncpg://sales_app:ci-app-password@localhost:5433/sales"
export DATABASE_URL_APP_ADMIN="postgresql+asyncpg://sales_app:ci-app-password@localhost:5433/sales"
export DATABASE_URL="postgresql+asyncpg://sales_app:ci-app-password@localhost:5433/sales"
export EMAIL_DELIVERY_ENABLED=false
export REDIS_URL="redis://localhost:6379/0"
export SECRETS_MASTER_KEY=$("D:/sales system/backend/.venv/Scripts/python.exe" -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())")

./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 &
API_PID=$!

for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/readyz)
  [ "$code" = "200" ] && break
  sleep 1
done
echo "api ready: $code"

cd "D:/sales system/frontend" || exit 1
export VITE_API_PROXY_TARGET="http://127.0.0.1:8001"
export BASE_URL="http://127.0.0.1:4173"
# vite preview started EXPLICITLY (playwright's webServer handshake proved
# flaky under this job model — connection refused on the first navigation).
npx vite preview --host 127.0.0.1 --port 4173 &
PREVIEW_PID=$!
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:4173/)
  [ "$code" = "200" ] && break
  sleep 1
done
echo "preview ready: $code"

npx playwright test e2e/deep-crawl.spec.js --reporter=list
CRAWL_EXIT=$?
kill $PREVIEW_PID 2>/dev/null

kill $API_PID 2>/dev/null
echo "crawl exit: $CRAWL_EXIT"
exit $CRAWL_EXIT
