#!/bin/sh
set -e

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

ROLE="${AGENT_ROLE:-api}"

if [ "$ROLE" = "worker" ]; then
  exec arq app.worker.WorkerSettings
fi

if [ "$ROLE" = "all" ]; then
  arq app.worker.WorkerSettings &
  WORKER_PID=$!
  trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT INT TERM
fi

exec uvicorn app.api:app \
  --host 0.0.0.0 \
  --port "${AGENT_PORT:-8642}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --limit-concurrency 512 \
  --timeout-keep-alive 30
