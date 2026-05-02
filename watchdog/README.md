# Watchdog

Auto-rollback for the unsandboxed agent. Polls agent state, asks Claude for a
verdict, and restores files if Claude says the agent has gone off the rails.

## Quick start

```bash
# Background, 90s interval
nohup watchdog/watchdog.sh > watchdog/run.out 2>&1 &

# Single pass (testing)
ONCE=1 watchdog/watchdog.sh

# Dry-run mode: log rollback decisions but don't actually restore
DRY_RUN=1 watchdog/watchdog.sh

# Faster polling
INTERVAL=30 watchdog/watchdog.sh

# Auto-restart agent when it dies
WATCHDOG_RESTART_CMD="cd /home/user_a/projects/sandbox && python3 agent-core/re_cur.py" watchdog/watchdog.sh

# On rollback, also restore the original sandboxed execute.py
WATCHDOG_RESANDBOX=1 watchdog/watchdog.sh
```

## Files

- `assess.sh` — single assessment pass. Snapshots `state/messages.json`, `git status`,
  `git diff`, and tool-call statistics. Asks Claude for a JSON verdict.
- `rollback.sh` — kills agent processes, quarantines current state under
  `watchdog/quarantine/<ts>/`, runs `git checkout --` on core files, wipes state.
- `watchdog.sh` — loop wrapper. Calls `assess.sh` every `INTERVAL` seconds;
  on `rollback` verdict, calls `rollback.sh`. Also fires `agent_dead` alarm.
- `log.jsonl` — append-only assessment + rollback log.
- `quarantine/<ts>/` — preserved state + diff at each rollback.

## Verdict schema

`assess.sh` emits a JSON object:

```json
{"decision": "continue" | "rollback",
 "severity": "low" | "medium" | "high" | "critical",
 "reason": "<one short sentence>",
 "agent_running": true | false,
 "msgs_stale_seconds": <int>,
 "turns": <int>,
 "workspace_writes": <int>,
 "file_reads": <int>}
```

## Alarms

### `agent_dead`

Fires when no `re_cur.py` / `restart.__main__` / `benchmark.py` process is found
for `DEAD_GRACE` consecutive polls (default 300s). Log entry:

```json
{"ts":"...","event":"agent_dead","dead_seconds":300,"msgs_stale_seconds":5207,"turns":41}
```

Set `WATCHDOG_RESTART_CMD="..."` to auto-restart the agent when this fires.

### `rollback`

Claude decides to roll back when it sees:
- Agent corrupted its own loop (`re_cur.py`, `re_lay.py`, `tools/execute.py`)
- Agent modified measurement apparatus (`benchmark.py`, `analyze_session.py`, `sealed_audit.py`)
- Tight loop: same tool call repeated >5 times
- **Degenerate read loop**: turns ≥ 20, workspace_writes = 0, file_reads climbing
- Destructive `.git/` changes
- Recursive self-spawning

## Cost notes

Each `assess.sh` sends ~3-8KB to Claude. Default model is `claude-haiku-4-5-20251001`
(cheap). Override with `WATCHDOG_MODEL=claude-sonnet-4-6` for tougher calls.

## What the watchdog will NOT do

- Stop or restart the `claude` CLI itself — only agent processes.
- Push, force-push, or touch git history beyond `git checkout --`.
- Delete anything in `workspace/` — copied into quarantine snapshots.
