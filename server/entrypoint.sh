#!/bin/sh
set -e
alembic upgrade head
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
  --limit-concurrency 64 \
  --timeout-keep-alive 30
