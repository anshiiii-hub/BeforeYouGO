#!/usr/bin/env bash
# Usage: scripts/dev.sh start|stop   (expects PostgreSQL reachable at DATABASE_URL)
set -euo pipefail
cd "$(dirname "$0")/../backend"
API_PORT="${API_PORT:-8001}"
case "${1:-start}" in
  start)
    .venv/bin/alembic upgrade head
    (cd ../frontend && npm run build)
    nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" > ../api.log 2>&1 &
    echo $! > ../api.pid; echo "http://127.0.0.1:$API_PORT" ;;
  stop) kill "$(cat ../api.pid)" && rm ../api.pid ;;
esac
