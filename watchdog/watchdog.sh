#!/usr/bin/env bash
# Continuous watchdog. Polls assess.sh on an interval. On a rollback verdict,
# invokes rollback.sh. Logs every assessment to log.jsonl.
#
# Usage:
#   watchdog/watchdog.sh                  # default 90s interval, runs forever
#   INTERVAL=30 watchdog/watchdog.sh
#   ONCE=1 watchdog/watchdog.sh           # single pass, no loop
#   DRY_RUN=1 watchdog/watchdog.sh        # never actually rolls back, just logs
#   WATCHDOG_RESANDBOX=1 watchdog/...     # restore sandbox on rollback
set -uo pipefail

REPO="${REPO:-/home/user_a/projects/sandbox}"
INTERVAL="${INTERVAL:-90}"
LOG="${WATCHDOG_LOG:-$REPO/watchdog/log.jsonl}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$REPO/watchdog"
touch "$LOG"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

run_once() {
  local verdict decision severity reason
  verdict=$("$HERE/assess.sh" 2>/dev/null)
  decision=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("decision","continue"))' 2>/dev/null || echo continue)
  severity=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("severity","low"))' 2>/dev/null || echo low)
  reason=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("reason",""))' 2>/dev/null || echo "")

  printf '{"ts":"%s","event":"assess","decision":"%s","severity":"%s","reason":%s}\n' \
    "$(ts)" "$decision" "$severity" \
    "$(printf '%s' "$reason" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
    >> "$LOG"

  if [ "$decision" = "rollback" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then
      printf '{"ts":"%s","event":"rollback_skipped_dry_run","reason":%s}\n' \
        "$(ts)" "$(printf '%s' "$reason" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
        >> "$LOG"
      echo "[$(ts)] DRY_RUN rollback: $reason" >&2
    else
      echo "[$(ts)] ROLLBACK: $reason" >&2
      "$HERE/rollback.sh" "$reason" >&2 || true
    fi
  else
    echo "[$(ts)] continue ($severity): $reason" >&2
  fi
}

if [ "${ONCE:-0}" = "1" ]; then
  run_once
  exit 0
fi

echo "[$(ts)] watchdog start, interval=${INTERVAL}s, log=$LOG" >&2
trap 'echo "[$(ts)] watchdog stop" >&2; exit 0' INT TERM

while true; do
  run_once
  sleep "$INTERVAL"
done
