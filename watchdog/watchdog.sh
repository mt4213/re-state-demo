#!/usr/bin/env bash
# Continuous watchdog. Polls assess.sh on an interval. On a rollback verdict,
# invokes rollback.sh. Also fires a separate `agent_dead` alarm when the agent
# process is missing — with optional auto-restart via WATCHDOG_RESTART_CMD.
#
# Usage:
#   watchdog/watchdog.sh                                 # default 90s loop
#   INTERVAL=30 watchdog/watchdog.sh
#   ONCE=1 watchdog/watchdog.sh                          # single pass
#   DRY_RUN=1 watchdog/watchdog.sh                       # log only, never act
#   WATCHDOG_RESANDBOX=1 watchdog/watchdog.sh            # restore sandbox on rollback
#   WATCHDOG_RESTART_CMD="..." watchdog/watchdog.sh      # auto-restart agent when dead
#   DEAD_GRACE=300 watchdog/watchdog.sh                  # seconds before agent_dead fires
set -uo pipefail

REPO="${REPO:-/home/user_a/projects/sandbox}"
INTERVAL="${INTERVAL:-90}"
LOG="${WATCHDOG_LOG:-$REPO/watchdog/log.jsonl}"
DEAD_GRACE="${DEAD_GRACE:-300}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$REPO/watchdog"
touch "$LOG"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
jstr() { python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))'; }

# Track consecutive dead checks so we only alarm once per outage
DEAD_STREAK=0
ALARMED=0

run_once() {
  local verdict decision severity reason agent_running msgs_stale turns ws_writes file_reads
  verdict=$("$HERE/assess.sh" 2>/dev/null)

  decision=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("decision","continue"))' 2>/dev/null || echo continue)
  severity=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("severity","low"))' 2>/dev/null || echo low)
  reason=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("reason",""))' 2>/dev/null || echo "")
  agent_running=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(str(json.load(sys.stdin).get("agent_running",False)).lower())' 2>/dev/null || echo false)
  msgs_stale=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("msgs_stale_seconds",-1))' 2>/dev/null || echo -1)
  turns=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("turns",0))' 2>/dev/null || echo 0)
  ws_writes=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("workspace_writes",0))' 2>/dev/null || echo 0)
  file_reads=$(printf '%s' "$verdict" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("file_reads",0))' 2>/dev/null || echo 0)

  printf '{"ts":"%s","event":"assess","decision":"%s","severity":"%s","reason":%s,"agent_running":%s,"msgs_stale_seconds":%s,"turns":%s,"workspace_writes":%s,"file_reads":%s}\n' \
    "$(ts)" "$decision" "$severity" "$(printf '%s' "$reason" | jstr)" \
    "$agent_running" "$msgs_stale" "$turns" "$ws_writes" "$file_reads" >> "$LOG"

  # --- Alarm: agent process is missing ---
  if [ "$agent_running" = "false" ]; then
    DEAD_STREAK=$((DEAD_STREAK + 1))
    # Only alarm once we've passed DEAD_GRACE seconds of consecutive dead polls
    local dead_seconds=$((DEAD_STREAK * INTERVAL))
    if [ "$dead_seconds" -ge "$DEAD_GRACE" ] && [ "$ALARMED" = "0" ]; then
      printf '{"ts":"%s","event":"agent_dead","dead_seconds":%s,"msgs_stale_seconds":%s,"turns":%s}\n' \
        "$(ts)" "$dead_seconds" "$msgs_stale" "$turns" >> "$LOG"
      echo "[$(ts)] !! AGENT DEAD for ${dead_seconds}s (turns=$turns, msgs_stale=${msgs_stale}s)" >&2
      ALARMED=1
      if [ -n "${WATCHDOG_RESTART_CMD:-}" ] && [ "${DRY_RUN:-0}" != "1" ]; then
        echo "[$(ts)] auto-restart: $WATCHDOG_RESTART_CMD" >&2
        printf '{"ts":"%s","event":"auto_restart","cmd":%s}\n' "$(ts)" "$(printf '%s' "$WATCHDOG_RESTART_CMD" | jstr)" >> "$LOG"
        bash -c "$WATCHDOG_RESTART_CMD" >> "$LOG.restart" 2>&1 &
      fi
    fi
  else
    if [ "$ALARMED" = "1" ]; then
      printf '{"ts":"%s","event":"agent_alive_again","turns":%s}\n' "$(ts)" "$turns" >> "$LOG"
      echo "[$(ts)] agent alive again (turns=$turns)" >&2
    fi
    DEAD_STREAK=0
    ALARMED=0
  fi

  # --- Rollback on verdict ---
  if [ "$decision" = "rollback" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then
      printf '{"ts":"%s","event":"rollback_skipped_dry_run","reason":%s}\n' \
        "$(ts)" "$(printf '%s' "$reason" | jstr)" >> "$LOG"
      echo "[$(ts)] DRY_RUN rollback: $reason" >&2
    else
      echo "[$(ts)] ROLLBACK ($severity): $reason" >&2
      "$HERE/rollback.sh" "$reason" >&2 || true
    fi
  else
    echo "[$(ts)] continue ($severity, running=$agent_running, turns=$turns, ws_w=$ws_writes, reads=$file_reads): $reason" >&2
  fi
}

if [ "${ONCE:-0}" = "1" ]; then
  run_once
  exit 0
fi

echo "[$(ts)] watchdog start, interval=${INTERVAL}s, dead_grace=${DEAD_GRACE}s, log=$LOG" >&2
trap 'echo "[$(ts)] watchdog stop" >&2; exit 0' INT TERM

while true; do
  run_once
  sleep "$INTERVAL"
done
