# AUDIT: sealed_audit.py (Tamper-Proof Logging)

## Purpose

`sealed_audit.py` provides an immutable audit trail that the agent cannot modify. It writes to a directory (`eval_results/`) that is NOT mounted inside the Docker container, ensuring research integrity.

## Security Model

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Container                         │
│  ┌──────────────┐            ┌──────────────┐               │
│  │ agent-core/  │            │  workspace/  │               │
│  │  (mounted)   │            │  (mounted)   │               │
│  └──────────────┘            └──────────────┘               │
│                                                               │
│  Agent can modify anything in mounted directories            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (CANNOT WRITE HERE)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Host Filesystem Only                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  eval_results/chats/sealed_audit_*.jsonl            │    │
│  │  (NOT mounted — agent cannot access)                │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Architecture

### Key Design Decisions

1. **Hard-coded path** — `/home/user_a/projects/sandbox/eval_results/chats`
   - Not configurable (security measure)
   - Path is outside Docker mount points

2. **Append-only JSONL format** — One JSON object per line
   - Atomic writes (no corruption on crash)
   - Easy to parse line-by-line
   - Cannot be modified (only appended to)

3. **Thread-safe writes** — Uses `threading.Lock`
   - Prevents concurrent write corruption
   - Important for multi-threaded environments

4. **Silent failure** — Exceptions are caught and ignored
   - Prevents recursion (logging failure would cause more logging)
   - Agent continues even if audit fails

## Functions

### `write_sealed_record(messages, stream_data=None)`

**Purpose:** Write an audit record after each state persist.

**Called from:** `re_cur.py` after:
- Initial state load
- Each LLM response
- Each tool execution

**Record format:**
```json
{
  "timestamp": "2026-05-03T21:30:42.123456",
  "messages_count": 42,
  "messages_preview": [
    {
      "role": "system",
      "content_len": 245,
      "tool_calls_count": 0
    },
    {
      "role": "assistant",
      "content_len": 0,
      "tool_calls_count": 1,
      "tools": ["file_write"]
    }
  ],
  "stream_done": true
}
```

**Location:** Lines 35-60

---

### `_preview_messages(messages, max_chars=500)`

**Purpose:** Create a safe preview of messages without exposing full content.

**Preview includes:**
- Role (system/assistant/tool)
- Content length
- First 100 chars of content
- Tool call count
- Tool names used

**Excludes:**
- Full content (to avoid bloat)
- Tool call arguments (may contain sensitive data)
- Internal metadata (`_thought`, `timestamp`)

**Tamper detection:** If agent changes `messages` from array to dict/object, logs:
```json
{
  "format": "non-array",
  "type": "dict",
  "keys": ["role", "content", ...]
}
```

**Location:** Lines 63-106

---

### `read_sealed_audit()`

**Purpose:** Read all audit records for analysis.

**Used by:** `analyze_session.py`, benchmark harness

**Behavior:**
- Returns list of JSON objects
- Skips malformed lines (JSON decode errors)
- Returns empty list if file doesn't exist

**Location:** Lines 109-122

---

## File Naming

### Pattern: `sealed_audit_{timestamp}.jsonl`

**Timestamp:** Unix epoch seconds (e.g., `1714777842`)

**Rotation:** New file created on process restart (timestamp changes)

**Location:** Lines 29-31

## State Management

### Global Variables

| Variable | Purpose |
|----------|---------|
| `_AUDIT_DIR` | Hard-coded audit directory path |
| `_AUDIT_FILE` | Current audit file path (set on first write) |
| `_lock` | Thread lock for concurrent writes |

**Note:** `_AUDIT_FILE` is `None` until first write. This allows multiple runs to create new files.

## Data Flow

```
re_cur.py: persist_state()
     │
     ▼
write_sealed_record(messages)
     │
     ▼
_preview_messages(messages) → safe preview
     │
     ▼
with _lock:
    open(audit_path, "a")
    write(json.dumps(record) + "\n")
```

## Integration Points

### Called From `re_cur.py`
1. Line 170: After initial state load
2. Line 404: After tool execution
3. Line 458: After no-tool error injection

### Not Called During
- LLM streaming (too noisy)
- Degeneration detection (internal)
- Implicit memory recall (transparent to agent)

## Error Handling

### Silent Failure Pattern
```python
try:
    # ... write audit record ...
except Exception as e:
    # Cannot log here — might cause recursion
    pass
```

**Rationale:** If audit logging fails, we don't want to crash the agent. The research data is lost, but the experiment continues.

**Downside:** No way to know if audit is failing.

### JSON Decode Errors in `read_sealed_audit()`
Malformed lines are silently skipped (line 121).

## Security Considerations

### Tamper-Proof Design
1. **Directory not mounted** — Agent cannot write to it
2. **Append-only format** — Existing records cannot be modified
3. **Hard-coded path** — Cannot be changed via environment variable

### Potential Vulnerabilities
1. **Host filesystem access** — Anyone with host access can modify audit logs
2. **No authentication** — No signature or checksum
3. **No encryption** — Logs are plain text

### Mitigations
- Run with minimal host access
- Use git to track audit logs
- Compare audit logs across runs

## Performance

### Thread Safety
- Uses `threading.Lock` for writes
- Minimal contention (writes are infrequent)

### Disk I/O
- One file write per turn
- Small records (~1-2 KB each)
- No buffering (each write is immediate)

### Storage Growth
- ~1-2 KB per turn
- 100 turns = ~100-200 KB
- 1000 runs = ~100-200 MB

## Configuration

### Not Configurable
The audit path is hard-coded for security reasons:
```python
_AUDIT_DIR = Path("/home/user_a/projects/sandbox/eval_results/chats")
```

### Why Not Configurable?
- If agent could change audit path, it could evade logging
- Hard-coded path ensures logs always go to same place

## Dependencies

| Module | Purpose |
|--------|---------|
| `json` | JSON serialization |
| `os` | File operations |
| `time` | Timestamp generation |
| `datetime` | ISO timestamp formatting |
| `pathlib.Path` | Path manipulation |
| `threading.Lock` | Thread safety |

## Known Quirks

1. **Silent failure** — No way to know if audit is working
2. **Hard-coded path** — Not portable to other systems
3. **No rotation** — File grows until process restart
4. **No checksum** — Tampering can only be detected by comparing to expected patterns

## Anti-Placebo Verification

The sealed audit is the foundation of anti-placebo verification:
- Agent self-report is unreliable
- Tool-use traces in audit log are ground truth
- `analyze_session.py` classifies behavior based on audit data, not agent claims

**Key Principle:** Trust the audit log, not the agent's narration.
