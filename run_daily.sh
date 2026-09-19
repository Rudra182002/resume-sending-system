#!/usr/bin/env bash
# Daily 9am run. Logs everything; never sends unless AUTO_SEND=true in .env.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs
STAMP=$(date +%Y-%m-%d)
{
  echo "=== run $(date -Is) ==="
  ./.venv/bin/python -m resume_bot run
  echo "=== exit $? at $(date -Is) ==="
} >> "logs/daily-$STAMP.log" 2>&1
find logs -name 'daily-*.log' -mtime +30 -delete
