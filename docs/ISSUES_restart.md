# ISSUES: Restart Daemon (Supervisor Process)

## Bugs

### None Known
No confirmed bugs at this time.

## Design Concerns

### 1. Exit Code 1 Treated as Crash
**Issue:** Agent exits with code 1 for all terminations, including natural completion.

**Impact:**
- Natural completion triggers crash context extraction
- Crash context written for successful runs
- No way to distinguish "agent finished" from "agent crashed"

**Question:** Should re_cur use exit(0) for natural completion?

**Location:** `daemon.py` line 231

---

### 2. No Crash Type Differentiation
**Issue:** All failures handled identically — no distinction between circuit breaker types.

**Impact:**
- Can't analyze which breaker triggers most
- Can't adapt recovery strategy to failure type
- Crash context doesn't include exit reason

**Question:** Should crash context include circuit breaker type?

**Location:** `daemon.py` lines 231-254

---

### 3. Crash Context Overwritten
**Issue:** New crash replaces old `.crash_context.log` — no history.

**Impact:**
- Only learn from most recent crash
- Can't analyze crash patterns over time
- Lost data if multiple crashes in quick succession

**Question:** Should we keep crash history (e.g., `crash_context_1.log`, `crash_context_2.log`)?

**Location:** `daemon.py` line 247

---

### 4. Health Check Required for Pre-Health
**Issue:** If pre-health command has no `health_url`, health wait is skipped entirely.

**Impact:**
- May start agent before pre-health is ready
- No validation that pre-health actually started
- Race condition possible

**Question:** Should health check be mandatory for pre-health?

**Location:** `daemon.py` lines 168-196

---

### 5. No Crash Context on Exit(0)
**Issue:** Only non-zero exits trigger crash context extraction.

**Impact:**
- "Successful" runs leave no crash context
- Can't analyze what went right vs wrong
- Incomplete data for research

**Question:** Should we always write crash context, even on success?

**Location:** `daemon.py` line 231

---

### 6. Environmental State 25k Char Limit
**Issue:** Crash context truncated at 25k characters.

**Impact:**
- May lose important context from long sessions
- Truncation may cut mid-event
- No warning when truncation happens

**Question:** Is 25k chars the right limit? Should it be configurable?

**Location:** `log_utils.py` lines 163-171

---

### 7. Log Cleaner May Hide Important Info
**Issue:** Cleaner suppresses repetitive Docker events and deduplicates logs.

**Impact:**
- May suppress error patterns that indicate systemic issues
- "Suppressed" marker doesn't show what was suppressed
- May lose count of how many times something happened

**Question:** Should suppressed events be counted and reported?

**Location:** `cleaner.py` lines 54-57, 66-81

---

### 8. No Validation of Crash Context File
**Issue:** If crash context file is corrupt or malformed, agent will fail to load it.

**Impact:**
- Agent startup may fail
- No error handling for bad crash context
- Silent failure (exception in `load_episodic_memory()`)

**Question:** Should we validate crash context before setting env var?

**Location:** `daemon.py` line 250, `re_cur.py` lines 128-150

---

## Potential Improvements

### 1. Crash Type Detection
Pass exit reason through environment:
```python
p.env = {
    "CRASH_CONTEXT_PATH": crash_ctx_file,
    "CRASH_REASON": "circuit_breaker_no_tool"
}
```

---

### 2. Crash History
Keep N most recent crash contexts:
```python
crash_history = deque(maxlen=5)
crash_history.rotate(1)
crash_history[0] = new_context
```

---

### 3. Crash Context on Success
Always write context, even on exit(0):
```python
if exit_code != 0 or ALWAYS_WRITE_CRASH_CONTEXT:
    # ... extract context ...
```

---

### 4. Configurable Limits
Make truncation limits configurable:
```json
{
  "crash_context": {
    "max_environmental_chars": 25000,
    "max_errors": 10,
    "max_command_length": 500
  }
}
```

---

### 5. Crash Context Validation
Validate before writing:
```python
try:
    json.loads(payload)
except ValueError:
    logger.error("Invalid crash context JSON")
    return
```

---

### 6. Suppressed Event Counting
Track and report suppressed events:
```python
suppressed_counts = {}
# ... in cleaner ...
suppressed_counts[msg] = suppressed_counts.get(msg, 0) + 1
# ... report periodically ...
```

---

## Questions for Further Investigation

1. **What is the most common crash reason?** Do we have data on this?

2. **How often does crash context actually help recovery?** Do agents adapt based on it?

3. **Is 25k chars enough for environmental state?** How often is it truncated?

4. **Should crash context be structured (JSON) instead of plain text?** Would enable better analysis.

5. **How many crashes typically occur before agent stabilizes?** Should backoff be more aggressive?

6. **Is the health check actually necessary?** Does it ever catch real problems?

---

## Edge Cases

### 1. Crash Context File Already Exists
**Behavior:** Overwritten without warning.

**Question:** Should we preserve or backup existing?

---

### 2. Log File Doesn't Exist
**Behavior:** `parse_crash_context()` returns `{"error": "Target log not found"}`.

**Handled:** Daemon continues without crash context.

**Location:** `log_utils.py` lines 58-59

---

### 3. Empty Crash Context
**Behavior:** Agent loads empty string as memory.

**Handled:** `load_episodic_memory()` returns None for empty.

**Location:** `re_cur.py` lines 143-144

---

### 4. Health Check Never Returns 200
**Behavior:** Retries until `health_max_retries` exhausted, then exits.

**Question:** Is this the right behavior? Should it wait forever?

**Location:** `daemon.py` lines 176-187

---

### 5. Process Exits Immediately (Exit Code 0)
**Behavior:** Treated as success, no restart, no crash context.

**Question:** But agent always exits with code 1. Is this case possible?

**Location:** `daemon.py` line 257

---

## Performance Considerations

### Log Parsing
- Reads last 2000 lines by default
- For large logs, uses deque for efficiency
- Flattens escaped newlines before parsing

**Optimization:** 2000 lines is reasonable for most logs.

### Log Cleaning
- Single pass through input file
- Maintains state in memory (last_msg, counts)
- Writes directly to output file

**Optimization:** Already efficient.

### Backoff Delays
- Maximum 60 seconds between restarts
- Exponential backoff: 1, 2, 4, 8, 16, 32, 60, 60, ...

**Question:** Should max_backoff be configurable?

---

## Security Considerations

### Crash Context File Permissions
**Issue:** Created with default umask, may be world-readable.

**Impact:** Crash context may contain sensitive information (commands, errors).

**Mitigation:** Set restrictive permissions (0600) on file creation.

---

### Config File Validation
**Issue:** Only validates structure, not values.

**Impact:** Could set `logfile` to sensitive location, `health_url` to internal service.

**Mitigation:** Validate paths are within expected directory.

---

### Environment Variable Injection
**Issue:** Sets `CRASH_CONTEXT_PATH` in process env.

**Impact:** Child processes inherit this path.

**Mitigation:** Use `env` dict instead of modifying `os.environ`.

---

## Dependencies Status

| Module | Purpose | Required |
|--------|---------|----------|
| `json` | Config parsing | Yes |
| `argparse` | CLI arguments | Yes |
| `threading` | Shutdown event | Yes |
| `signal` | Signal handlers | Yes |
| `time` | Sleep/delays | Yes |
| `urllib.request` | Health checks | Yes |
| `re` | Log parsing | Yes |
| `ManagedProcess` | Process wrapper | Yes |

---

## Testing Gaps

### No Unit Tests
- No tests for `parse_crash_context()`
- No tests for `clean_log()`
- No tests for backoff logic

### No Integration Tests
- No tests for full restart cycle
- No tests for crash context injection
- No tests for health check failures

### Manual Testing Only
- All verification is manual
- No automated regression testing

---

## Documentation Gaps

### Missing
- No docstring for `validate_config()`
- No docstring for `_wait_for_health()`
- No explanation of backoff algorithm in code

### Present
- Module-level docstrings
- Some inline comments
- Function docstrings for key functions

---

## Research Integrity Notes

### What This Provides
- Crash recovery between sessions
- Crash context for learning
- Process supervision for long-running experiments

### What This Does NOT Provide
- Distinction between failure types
- Crash history for analysis
- Validation that crash context is actually useful

### Key Principle
The restart daemon ensures experiments keep running despite crashes, but doesn't guarantee the crash context is actually helpful for learning.
