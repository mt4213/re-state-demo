# Watchdog

Auto-rollback for the unsandboxed agent. Polls agent state, asks Claude for a
verdict, restores files if Claude says the agent has gone off the rails.

## Files

- `assess.sh` — single assessment pass. Snapshots `state/messages.json`,
  `git status`, `git diff agent-core/ benchmark.py analyze_session.py`, and
  asks Claude for a JSON verdict. Prints verdict to stdout.
- `rollback.sh` — kills agent processes, quarantines current state under
  `watchdog/quarantine/<ts>/`, runs `git checkout -- agent-core/ benchmark.py
  analyze_session.py`, wipes `state/messages.json` and `state/stream.json`.
- `watchdog.sh` — loop wrapper. Calls `assess.sh` every `INTERVAL` seconds;
  on `rollback` verdict, calls `rollback.sh`.
- `log.jsonl` — append-only assessment + rollback log.
- `quarantine/<ts>/` — preserved state + diff at each rollback.

## Quick start

```bash
# Background, 90s interval
nohup watchdog/watchdog.sh > watchdog/run.out 2>&1 &

# Single pass (handy for testing)
ONCE=1 watchdog/watchdog.sh

# Dry-run mode: log rollback decisions but don't actually restore
DRY_RUN=1 watchdog/watchdog.sh

# Faster polling
INTERVAL=30 watchdog/watchdog.sh

# On rollback, also restore the original sandboxed execute.py
WATCHDOG_RESANDBOX=1 watchdog/watchdog.sh
```

## Verdict schema

`assess.sh` always emits a single JSON object:

```json
{"decision": "continue" | "rollback",
 "severity": "low" | "medium" | "high" | "critical",
 "reason": "<one sentence>"}
```

If Claude returns nothing or invalid JSON, the watchdog defaults to
`continue` and logs the reason — it never rolls back on its own confusion.

## Cost notes

Each `assess.sh` call sends ~3-8KB of context to Claude. Default model is
`claude-haiku-4-5-20251001` (cheap). Override with
`WATCHDOG_MODEL=claude-sonnet-4-6 watchdog/watchdog.sh` for tougher calls.

At 90s interval with Haiku, expect a few US cents per hour.

## What the watchdog will *not* do

- It will not stop or restart the `claude` CLI itself — only `re_cur.py`,
  `restart.__main__`, and `benchmark.py` processes.
- It will not push, force-push, or touch git history beyond `git checkout --`
  on tracked files.
- It will not delete anything in `workspace/` — the agent's experimental
  scratch is sacred. Workspace is *copied* into the quarantine snapshot.

## Tuning the verdict prompt

The criteria for rollback are inline in `assess.sh`. Edit there. Keep them
narrow — the experiment *is* an unsandboxed agent, so most behavior should
be allowed to continue.
