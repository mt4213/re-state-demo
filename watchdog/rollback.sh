#!/usr/bin/env bash
# Stop the agent, restore code to last committed state, restore unsandbox
# backup if needed, and log the action. Idempotent.
set -uo pipefail

REPO="${REPO:-/home/user_a/projects/sandbox}"
LOG="${WATCHDOG_LOG:-$REPO/watchdog/log.jsonl}"
REASON="${1:-no-reason-given}"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() {
  printf '{"ts":"%s","event":"rollback","reason":%s,"detail":%s}\n' \
    "$(ts)" "$(printf '%s' "$REASON" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
    "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
    >> "$LOG"
}

cd "$REPO" || exit 1

# 1. Kill running agent processes (do NOT touch claude CLI itself)
killed=$(pgrep -fa "re_cur\.py|restart\.__main__|benchmark\.py" 2>/dev/null || true)
if [ -n "$killed" ]; then
  pkill -f "re_cur\.py" 2>/dev/null || true
  pkill -f "restart\.__main__" 2>/dev/null || true
  pkill -f "benchmark\.py" 2>/dev/null || true
  sleep 1
  pkill -9 -f "re_cur\.py" 2>/dev/null || true
  pkill -9 -f "restart\.__main__" 2>/dev/null || true
fi

# 2. Stash any in-flight workspace work the agent did, so we don't lose data
mkdir -p "$REPO/watchdog/quarantine"
qdir="$REPO/watchdog/quarantine/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$qdir"
cp -a "$REPO/agent-core/state" "$qdir/state" 2>/dev/null || true
cp -a "$REPO/workspace" "$qdir/workspace" 2>/dev/null || true
git -C "$REPO" diff agent-core/ benchmark.py analyze_session.py > "$qdir/diff.patch" 2>/dev/null || true

# 3. Restore tracked files to HEAD
git -C "$REPO" checkout -- agent-core/ benchmark.py analyze_session.py 2>/dev/null || true

# 4. Restore execute.py from the unsandbox backup if user wants the sandbox
#    back. Disabled by default: the *experiment* is unsandboxed. Set
#    WATCHDOG_RESANDBOX=1 to force.
if [ "${WATCHDOG_RESANDBOX:-0}" = "1" ] && [ -f "$REPO/unsandbox_backup/execute.py.backup" ]; then
  cp "$REPO/unsandbox_backup/execute.py.backup" "$REPO/agent-core/tools/execute.py"
fi

# 5. Wipe state so next start is clean
rm -f "$REPO/agent-core/state/messages.json" "$REPO/agent-core/state/stream.json" 2>/dev/null || true

detail="killed=$(printf '%s' "$killed" | wc -l) quarantine=$qdir"
log "$detail"
echo "rollback done -> $qdir"
