# AUDIT: Restart Daemon (Supervisor Process)

## Purpose

The restart daemon is a generic supervisor that:
1. Starts a pre-health command (e.g., Docker llama.cpp)
2. Waits for health endpoint to respond
3. Starts a post-health command (e.g., agent)
4. Monitors both processes
5. Restarts on failure with exponential backoff
6. Extracts crash context and injects it into next run

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Restart Daemon                            │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐      ┌──────────────┐                     │
│  │ Pre-Health   │      │ Post-Health  │                     │
│  │ (Docker)     │      │ (Agent)      │                     │
│  └──────┬───────┘      └──────┬───────┘                     │
│         │                     │                              │
│         ▼                     ▼                              │
│  ┌──────────────────────────────────────┐                   │
│  │     Health Check Endpoint            │                   │
│  │     (pre_health_command.health_url)  │                   │
│  └──────────────────────────────────────┘                   │
│                                                               │
│  Process Loop:                                                │
│    1. Check if processes running                              │
│    2. If crashed: extract crash context                      │
│    3. Write .crash_context.log                               │
│    4. Set CRASH_CONTEXT_PATH env var                          │
│    5. Wait backoff seconds                                    │
│    6. Restart process                                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. `daemon.py` — Main Supervisor Loop

**Responsibilities:**
- Process lifecycle management
- Health check polling
- Crash context extraction
- Backoff scheduling
- Signal handling (SIGINT, SIGTERM)

**Entry point:** `main()` function

---

### 2. `log_utils.py` — Crash Context Extraction

**Responsibilities:**
- Parse log files for crash information
- Extract last command, fatal errors, environmental state
- Session isolation via `AGENT_SESSION_MARKER`

**Key function:** `parse_crash_context(log_path)`

---

### 3. `cleaner.py` — Log Noise Reduction

**Responsibilities:**
- Remove repetitive log lines
- Truncate long messages
- Filter out non-critical Docker events
- Normalize PIDs and timestamps

**Key function:** `clean_log(input_file, output_file)`

---

## Configuration

### File Format (JSON)
```json
{
  "pre_health_command": {
    "name": "docker",
    "command": "/path/to/docker/start.sh",
    "health_url": "http://localhost:8080/health",
    "health_timeout": 300,
    "health_poll_interval": 2,
    "health_max_retries": 0
  },
  "post_health_command": {
    "name": "agent",
    "command": "/path/to/agent/start.sh",
    "max_restarts": 0
  },
  "logfile": "logs/restart_daemon.log",
  "cleaned_log": "logs/cleaned.log",
  "crash_context_file": ".crash_context.log",
  "log_max_bytes": 10000000,
  "log_backup_count": 3,
  "quiet": true
}
```

### Key Options

| Option | Purpose | Default |
|--------|---------|---------|
| `pre_health_command` | Command to run before agent (optional) | None |
| `post_health_command` | Command to run after health (required) | Required |
| `health_url` | Health check endpoint | None |
| `health_timeout` | Max seconds to wait for health | 300 |
| `logfile` | Daemon log file | restart_daemon.log |
| `cleaned_log` | Cleaned log for crash parsing | logs/cleaned.log |
| `crash_context_file` | Path to crash context output | .crash_context.log |
| `max_restarts` | Max restarts before giving up | 0 (unlimited) |

## Restart Logic

### When to Restart

A process is restarted if:
1. It exits with non-zero code
2. It crashes (unexpected termination)
3. Health check fails (for pre-health command)

### When to Stop (Exit)

The daemon stops if:
1. SIGINT/SIGTERM received
2. `max_restarts` limit reached
3. Health check fails after max retries
4. Unrecoverable config error

### Backoff Algorithm

```
backoff = min(previous_backoff * 2, MAX_BACKOFF)
reset if runtime >= 30 seconds
```

**Constants:**
- `INITIAL_BACKOFF = 1.0` seconds
- `MAX_BACKOFF = 60.0` seconds
- `RESET_AFTER = 30.0` seconds

**Location:** `daemon.py` lines 277-283

## Crash Context Extraction

### Trigger
Process exits with non-zero code (line 231):
```python
if exit_code != 0 and post_cfg and p.name == post_cfg.get("name"):
```

### Process
1. Clear old env vars (no stale context)
2. Run log cleaner if `cleaned_log` configured
3. Parse crash context from log
4. Write to `crash_context_file`
5. Set `CRASH_CONTEXT_PATH` env var for next run

### Output Format (`.crash_context.log`)
```
Last action: {last_command}

Recent events:
{environmental_state}

Fatal errors:
{fatal_errors}
```

**Location:** `daemon.py` lines 81-103

## Log Parsing (`log_utils.py`)

### `parse_crash_context()`

**Input:** Cleaned log file path

**Output:**
```python
{
    "last_command": str or None,      # Last executed command
    "fatal_errors": [str, ...],       # Recent error lines
    "environmental_state": [str, ...], # Recent interaction events
    "error": str (on failure)
}
```

**Extraction Strategy:**
1. Read last N lines (default: 2000)
2. Trim to latest session after `AGENT_SESSION_MARKER`
3. Parse events: `[ACT]`, `[OBS]`, `[USER]`, `[THINK]`
4. Find 3rd-to-last ACTION event
5. Collect all events from that point
6. Truncate at 25k characters

**Location:** `log_utils.py` lines 38-180

## Log Cleaning (`cleaner.py`)

### `clean_log(input_file, output_file, max_len=500)`

**Transformations:**
1. **Deduplication:** Collapse repeated lines (show count)
2. **Length truncation:** Limit to 500 chars per line
3. **Docker filtering:** Skip non-error Docker logs
4. **Normalization:** Replace PIDs, timestamps with placeholders
5. **Suppression:** After 3 identical events, mark as suppressed

**Location:** `cleaner.py` lines 3-84

## Health Check Flow

```
Start pre-health command
     │
     ▼
Poll health_url every 2 seconds
     │
     ├─▶ 200 OK → Continue to post-health
     │
     ├─▶ Timeout/Error → Increment retry count
     │                     │
     │                     ▼
     │              retry < max_retries?
     │                     │
     │                     ├─▶ Yes → Wait, restart process, retry
     │                     └─▶ No → EXIT (fatal)
     │
     └─▶ After health_timeout → EXIT (fatal)
```

**Location:** `daemon.py` lines 54-78

## Dependency Management

### Docker Dies → Agent Dies
If pre-health command (Docker) crashes:
1. Stop post-health command (agent)
2. Wait for Docker to recover
3. Wait for health check
4. Then restart agent

**Location:** `daemon.py` lines 221-227

## Signal Handling

### Supported Signals
- `SIGINT` (Ctrl+C)
- `SIGTERM` (kill)

### Behavior
1. Set `stopping` event
2. Stop all child processes
3. Run log cleaner one final time
4. Exit cleanly

**Location:** `daemon.py` lines 156-163, 308-312

## Environment Variable Injection

### Crash Context Path
When a process crashes:
1. Crash context written to file
2. `CRASH_CONTEXT_PATH` env var set to file path
3. Next restart inherits this env var
4. Agent's `load_episodic_memory()` reads it

**Location:** `daemon.py` line 250

## Session Isolation

### `AGENT_SESSION_MARKER`
```
=== AGENT SESSION START ===
```

**Purpose:** Marks the start of each agent session in the log.

**Used by:** `log_utils._trim_to_latest_session()` to isolate crashes to single session.

**Location:** `daemon.py` line 204, `log_utils.py` line 11

## State Management

### Global State (daemon.py)
- `stopping` — threading.Event for shutdown signal
- `post_health_pending` — bool for Docker recovery state

### Per-Process State
- `backoff` — current backoff delay
- `restart_count` — number of restarts
- `last_start` — timestamp of last start
- `env` — dict of environment variables to inject

## Configuration Loading

### Via Command Line
```bash
python -m restart --config config.local.json
```

### Validation
`validate_config()` checks:
- `post_health_command` exists
- `post_health_command.command` is string
- `health_url` is string (if specified)
- Numeric values are positive
- `max_restarts` is non-negative integer

**Location:** `daemon.py` lines 24-51

## Error Handling

### Config Errors
Print to stderr, exit with code 1.

### Process Launch Failures
Log error, increment backoff, retry.

### Health Check Timeouts
Log error, retry if under limit, else exit.

### Crash Context Parse Failures
Log exception, continue without crash context.

## Logging

### Log Rotation
- `log_max_bytes`: 10 MB default
- `log_backup_count`: 3 files default
- Uses `logging.handlers.RotatingFileHandler`

### Quiet Mode
If `quiet: true` in config:
- Suppress lifecycle messages from terminal
- Keep messages in log file

**Location:** `daemon.py` lines 142-147

## Dependencies

| Module | Purpose | Required |
|--------|---------|----------|
| `json` | Config parsing | Yes |
| `argparse` | CLI argument parsing | Yes |
| `threading` | Event for shutdown signal | Yes |
| `signal` | Signal handlers | Yes |
| `time` | Sleep/delays | Yes |
| `urllib.request` | Health check HTTP requests | Yes |
| `re` | Log parsing | Yes |
| `ManagedProcess` | Process management | Yes |

## Known Quirks

1. **Exit code 1 treated as crash** — Clean agent exit also triggers crash context
2. **No diff between crash types** — All failures treated identically
3. **Health check required for pre-health** — If pre-health has no health_url, skipped
4. **Crash context overwritten** — New crash replaces old (no history)
5. **No crash context on exit(0)** — Only non-zero exits trigger extraction

## Files Created

### Runtime Files
- `restart_daemon.log` — Main daemon log
- `cleaned.log` — Cleaned log for parsing
- `.crash_context.log` — Crash context payload
- `.crash_context.log.tmp` — Atomic write temp file

### Location
All files in same directory as config file.

## Integration with Agent

### Agent Side
- `re_cur.py` calls `load_episodic_memory()` on startup
- Checks `CRASH_CONTEXT_PATH` env var
- If file exists, reads and compresses via `re_scribe`
- Injects as system message

### Daemon Side
- Waits for agent to exit
- If `exit_code != 0`: extracts crash context
- Writes to `.crash_context.log`
- Sets `CRASH_CONTEXT_PATH` env var
- Restarts agent with crash context available

**Location:** `daemon.py` lines 231-254
