#!/usr/bin/env bash
# Daily pipeline. Safe to call repeatedly - skips if it already ran today, so a
# laptop that was off at 09:00 still catches up whenever it comes back on.
#   ./run_daily.sh           run only if today's run has not happened
#   ./run_daily.sh --force   run regardless
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs
STAMP_FILE="logs/.last_run"
TODAY=$(date +%Y-%m-%d)

if [ "${1:-}" != "--force" ] && [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$TODAY" ]; then
  echo "already ran today ($TODAY) - use --force to run anyway"
  exit 0
fi

LOG="logs/daily-$TODAY.log"
{
  echo "=== run $(date -Is) ==="
  ./.venv/bin/python -m resume_bot harvest 3     # alert mail: LinkedIn / Naukri / foundit
  ./.venv/bin/python -m resume_bot agents 60 6   # ingest, score, research, tailor, render
  echo "=== finished $(date -Is) ==="
} >> "$LOG" 2>&1

echo "$TODAY" > "$STAMP_FILE"
tail -8 "$LOG"
find logs -name 'daily-*.log' -mtime +30 -delete 2>/dev/null || true
