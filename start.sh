#!/bin/bash
# Start the Hangul API: apply database migrations, then serve.
#
#   RUN_MIGRATIONS=1  (default) run `alembic upgrade head` first; set 0 to skip
#   PORT              (default 8000)
#   WEB_CONCURRENCY   (default 1) uvicorn workers. Keep 1 while SCHEDULER_ENABLED
#                     is true: every worker would run the scheduler, and it isn't
#                     safe to run twice (tasks and reminders would go out twice).
set -euo pipefail

if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
  echo "→ alembic upgrade head"
  alembic upgrade head
fi

# No --proxy-headers on purpose: the admin IP allowlist ignores X-Forwarded-For
# (CLAUDE.md), and the API is only reachable from the web container anyway.
exec uvicorn harness.api.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --no-proxy-headers \
  --timeout-keep-alive 75
