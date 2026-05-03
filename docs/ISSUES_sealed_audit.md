# ISSUES: sealed_audit.py (Tamper-Proof Logging)

## Bugs

### None Known
No confirmed bugs at this time.

## Design Concerns

### 1. Silent Failure
**Issue:** Exceptions are caught and ignored. No way to know if audit logging is working.

**Impact:**
- Research data could be lost without detection
- No way to verify audit integrity during run
- Could fail silently for entire experiment

**Question:** Should we log failures to stderr (outside audit system)?

**Location:** Lines 57-60

---

### 2. Hard-Coded Path
**Issue:** Audit path is hard-coded to `/home/user_a/projects/sandbox/eval_results/chats`.

**Impact:**
- Not portable to other systems
- Cannot run experiments from different directories
- Makes testing difficult

**Question:** Should this be configurable but validated?

**Location:** Line 20

---

### 3. No File Rotation
**Issue:** Audit file grows until process restart.

**Impact:**
- Very long runs could create huge files
- No way to limit disk usage
- Could fill disk if agent loops forever

**Question:** Should we rotate files after N records or size limit?

---

### 4. No Checksums or Signatures
**Issue:** Audit logs have no integrity protection.

**Impact:**
- Tampering can only be detected by pattern analysis
- No cryptographic proof of authenticity
- Host filesystem access allows modification

**Question:** Should we add HMAC signatures to each record?

---

### 5. Minimal Preview Data
**Issue:** `_preview_messages()` only captures role, content length, and tool names.

**Impact:**
- Limited visibility into agent behavior
- Cannot reconstruct full conversation from audit
- Tool arguments are not logged (may hide important context)

**Question:** Is this enough for research? Should we capture more?

**Location:** Lines 63-106

---

### 6. No Compression
**Issue:** Long conversations create large audit records.

**Impact:**
- Disk usage grows linearly with conversation length
- No compression for redundant data

**Question:** Should we compress older records or use delta encoding?

---

## Potential Improvements

### 1. Failure Notification
```python
except Exception as e:
    print(f"AUDIT FAILURE: {e}", file=sys.stderr)
    pass
```

---

### 2. Configurable but Validated Path
```python
_AUDIT_DIR = Path(os.getenv("SEALED_AUDIT_DIR",
    "/home/user_a/projects/sandbox/eval_results/chats"))
# Validate: must be outside /tmp, must be absolute path
```

---

### 3. File Rotation
Rotate after N records or size limit:
```python
_MAX_RECORDS = 10000
_MAX_SIZE = 100 * 1024 * 1024  # 100 MB
```

---

### 4. HMAC Signatures
Add cryptographic signature to each record:
```python
import hmac
import hashlib

key = os.getenv("AUDIT_HMAC_KEY")
signature = hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()
```

---

### 5. Verbose Mode
Add environment variable to log full messages (with consent):
```python
if os.getenv("AUDIT_VERBOSE") == "1":
    record["messages_full"] = messages
```

---

### 6. Metrics Endpoint
Add HTTP endpoint to query audit statistics:
- Total records
- Total tool calls by type
- Average conversation length

---

## Questions for Further Investigation

1. **How often does audit logging fail?** Have we ever seen silent failures?

2. **Is the preview data sufficient?** What analysis cannot be done with current preview?

3. **What is the typical audit file size?** Should we implement rotation?

4. **Could the agent evade audit by changing message format?** How do we detect this?

5. **Is host filesystem access a real security risk?** What protections exist?

---

## Edge Cases

### 1. Messages Is Not An Array
**Handled:** Logs format/type/keys for debugging.

**Question:** Should this trigger an alert?

**Location:** Lines 65-71

---

### 2. Audit Directory Cannot Be Created
**Behavior:** Silent failure (exception caught).

**Question:** Should we pre-create directory on import?

---

### 3. Disk Full
**Behavior:** Write fails, silent failure.

**Question:** Should we check available disk space before writing?

---

### 4. Corrupt Audit File
**Behavior:** `read_sealed_audit()` skips malformed lines.

**Question:** Should we report corruption statistics?

---

### 5. Concurrent Writes from Multiple Processes
**Behavior:** Thread lock protects within process, but not across processes.

**Question:** Should we use file locking (flock) for multi-process safety?

---

## Performance Considerations

### Current Characteristics
- ~1-2 KB per record
- One disk write per turn
- No buffering (immediate fsync)

### Optimization Opportunities
- Buffer writes and flush periodically
- Compress records before writing
- Use binary format instead of JSON

### Risks
- Buffering loses data on crash
- Compression adds CPU overhead
- Binary format reduces human readability

---

## Security Considerations

### Current Protections
- Directory not mounted in container
- Append-only format
- Hard-coded path

### Remaining Risks
- Anyone with host access can modify logs
- No authentication or authorization
- No encryption (sensitive data in plain text)

### Mitigations
- Run with minimal host access
- Use git to track audit logs
- Encrypt at rest (filesystem encryption)
- Restrict host permissions

---

## Dependencies Status

| Dependency | Purpose | Required |
|------------|---------|----------|
| `json` | JSON serialization | Yes |
| `os` | File operations | Yes |
| `time` | Timestamp generation | Yes |
| `datetime` | ISO formatting | Yes |
| `pathlib.Path` | Path manipulation | Yes |
| `threading.Lock` | Thread safety | Yes |

---

## Testing Gaps

### No Unit Tests
- No tests for `_preview_messages()`
- No tests for `write_sealed_record()`
- No tests for `read_sealed_audit()`

### No Integration Tests
- No tests for concurrent writes
- No tests for disk full scenarios
- No tests for corrupt files

### Manual Testing Only
- All verification is manual
- No automated regression testing

---

## Documentation Gaps

### Missing
- No docstring for `write_sealed_record()`
- No docstring for `read_sealed_audit()`
- No explanation of security model in code

### Present
- Module-level docstring with security explanation
- Some inline comments
- Function docstrings for `_preview_messages()`

---

## Research Integrity Notes

### What This Protects Against
- Agent modifying its own history
- Agent hiding its actions
- Placebo effects (agent claiming it did X when it did Y)

### What This Does NOT Protect Against
- Host filesystem tampering
- Measurement apparatus bugs
- Researcher bias in interpretation

### Key Principle
The sealed audit provides **observable data** that can be analyzed objectively. Agent self-report is treated as unreliable narrative.
