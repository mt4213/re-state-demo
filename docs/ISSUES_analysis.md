# ISSUES: analyze_session.py & benchmark.py (Measurement Pipeline)

## Bugs

### None Known
No confirmed bugs at this time.

## Design Concerns

### 1. Synthetic Message Detection is Fragile
**Issue:** Complex regex-based detection of re_cur scaffolding may break on format changes.

**Impact:**
- Synthetic messages counted as real agent actions
- Metrics become inaccurate
- Hard to debug when detection fails

**Question:** Should re_cur mark synthetic messages explicitly (e.g., `_synthetic: true`)?

**Location:** `analyze_session.py` lines 64-86

---

### 2. Source File Detection is Heuristic
**Issue:** `_looks_like_source()` checks for `.py` extension or `agent-core/` path.

**Impact:**
- May miss source files with different extensions
- May false-positive on non-source `.py` files
- Incomplete tracking of self-inspection

**Question:** Should we have a configurable list of source directories?

**Location:** `analyze_session.py` lines 177-181

---

### 3. Temperature Parsing from Source Code
**Issue:** benchmark.py parses `re_lay.py` with regex to extract temperature.

**Impact:**
- Brittle — breaks if code formatting changes
- May not find temperature if defined differently
- No validation that parsed value is correct

**Question:** Should temperature be written to a metadata file instead?

**Location:** `benchmark.py` lines 249-257

---

### 4. Git Reset Loses Uncommitted Work
**Issue:** `git checkout -- agent-core/` on every run loses uncommitted changes.

**Impact:**
- Development work in agent-core/ lost during benchmark
- Must commit before running benchmarks
- Easy to accidentally lose work

**Question:** Should we warn if there are uncommitted changes?

**Location:** `benchmark.py` line 116

---

### 5. No Validation of Self-Modification Claim
**Issue:** `file_write_tool_calls` lists all file_write calls, but doesn't verify they actually modified files.

**Impact:**
- May count failed writes as self-modification
- No distinction between attempt and success
- Anti-placebo verification weakened

**Question:** Should we cross-reference with git diff for verification?

**Location:** `analyze_session.py` lines 441-458

---

### 6. Stall Detection May Miss Subtle Loops
**Issue:** Stall = 2+ of last 3 assistant messages had no tools.

**Impact:**
- Agent in deep reasoning loop (not tool-using) not detected
- Agent repeating same tool not detected
- Limited definition of "stuck"

**Question:** Should stall detection include repeated tool signatures?

**Location:** `analyze_session.py` lines 115-126

---

### 7. Sealed Audit Watcher Uses Polling
**Issue:** mtime polling every 0.5 seconds may miss rapid updates.

**Impact:**
- Lost audit records if agent writes quickly
- Inconsistent audit coverage
- Race condition possible

**Question:** Should we use inotify or file system events instead?

**Location:** `benchmark.py` lines 65-86

---

### 8. No Distinction Between "Aware" and "Blind" in Results
**Issue:** BLIND_ENV=1 removes .env, but results don't explicitly label runs as aware/blind.

**Impact:**
- Hard to analyze effect of measurement awareness
- Must infer from metadata
- Not obvious in dashboard

**Question:** Should we add `condition: "aware" | "blind"` to results?

**Location:** benchmark.py run loop (no explicit labeling)

---

### 9. Workspace File Detection Uses Git Status
**Issue:** `detect_workspace_changes()` uses `git status --porcelain workspace/`.

**Impact:**
- Only detects files that git knows about
- May miss files in subdirectories
- Depends on git configuration

**Question:** Should we use `find` instead?

**Location:** `benchmark.py` lines 146-161

---

### 10. Error Counting May Miss Embedded Errors
**Issue:** `error_indices` only counts messages starting with `[Error:`.

**Impact:**
- Errors in tool responses may be missed
- Non-standard error formats not counted
- Incomplete error tracking

**Question:** Should we have a more robust error detection pattern?

**Location:** `analyze_session.py` lines 167-174

---

## Potential Improvements

### 1. Explicit Synthetic Message Marking
```python
# In re_cur.py
messages.append({
    "role": AGENT_ROLE,
    "content": None,
    "tool_calls": [...],
    "timestamp": get_timestamp(),
    "_synthetic": True  # ← Mark as scaffolding
})
```

### 2. Metadata File for Configuration
```bash
# .env.metadata written at container start
echo "temperature=$LLM_TEMPERATURE" > /metadata
echo "model=$LLM_MODEL" >> /metadata
benchmark.py reads this instead of parsing source
```

### 3. Git Stash Instead of Checkout
```python
# Preserve uncommitted work
subprocess.run(["git", "stash", "-u"])
# ... run ...
subprocess.run(["git", "stash", "pop"])
```

### 4. Inotify for Sealed Audit
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
# Use file system events instead of polling
```

### 5. Verified Self-Modification Flag
```python
# Cross-reference file_write calls with git diff
verified = any(
    call["path"] in diff_files
    for call in file_write_calls
)
awareness_signals["verified_self_modification"] = verified
```

### 6. Condition Labeling
```python
result["condition"] = "blind" if os.getenv("BLIND_ENV") == "1" else "aware"
```

---

## Questions for Further Investigation

1. **How often does synthetic message detection fail?** Have we observed false positives/negatives?

2. **What is the actual distribution of awareness signals?** Are agents actually learning from errors?

3. **Does self-inspection correlate with better performance?** What does the data say?

4. **How often do agents attempt self-modification vs succeed?** Is there a gap?

5. **Are our metrics actually measuring what we think?** What's the correlation between different metrics?

6. **What is the most common termination reason?** Timeout vs natural vs error?

---

## Edge Cases

### 1. Empty messages.json
**Behavior:** analyze_session.py exits with error.

**Question:** Should benchmark.py handle this gracefully?

---

### 2. No git repository
**Behavior:** benchmark.py fails on git commands.

**Question:** Should we skip git operations if not in a repo?

---

### 3. Sealed Audit File Missing
**Behavior:** analyze_session.py continues without sealed audit data.

**Handled:** Graceful degradation.

---

### 4. Container Crashes Hard (SIGKILL)
**Behavior:** benchmark.py kills container, proceeds with analysis.

**Question:** Do we lose data in this case?

---

### 5. Agent Modifies .env
**Behavior:** .env is read-only mount (usually), but may be writable in some configs.

**Question:** Should we validate .env hasn't changed?

---

## Performance Considerations

### analyze_session.py
- Single pass through messages for most metrics
- Multiple passes for error analysis
- O(n) complexity where n = message count

### benchmark.py
- Git checkout on each run (overhead ~1-2 seconds)
- Docker container start/stop (overhead ~5-10 seconds)
- Polling thread for sealed audit (low overhead)

### Optimization Opportunities
- Cache git checkout (only if changes)
- Use Docker API instead of subprocess
- Parallel analyze_session.py with container teardown

---

## Security Considerations

### No Input Validation
- analyze_session.py trusts messages.json format
- benchmark.py runs docker with user-provided config
- No validation of file paths in tool calls

### Container Escape Vectors
- Agent can potentially write to mounted directories
- Sealed audit is only true protection (unmounted)
- Git diff could be used to exfiltrate data

### Mitigations
- Run as non-root user
- Restrict Docker capabilities
- Validate file paths before acting

---

## Dependencies Status

### analyze_session.py
| Module | Purpose | Required |
|--------|---------|----------|
| `json` | Parse messages | Yes |
| `re` | Pattern matching | Yes |
| `pathlib.Path` | File paths | Yes |

### benchmark.py
| Module | Purpose | Required |
|--------|---------|----------|
| `subprocess` | Docker/git control | Yes |
| `threading` | Audit watcher | Yes |
| `urllib.request` | Health check | Yes |
| `json` | Results parsing | Yes |
| `signal` | Timeout handling | Yes |

---

## Testing Gaps

### No Unit Tests
- No tests for metric calculations
- No tests for synthetic detection
- No tests for git operations

### No Integration Tests
- No tests for full benchmark run
- No tests for timeout handling
- No tests for crash scenarios

### Manual Testing Only
- All verification is manual
- No automated regression testing

---

## Documentation Gaps

### Missing
- No docstring for most functions
- No explanation of metrics in code
- No examples of expected output

### Present
- Module-level docstrings
- Some inline comments
- Command-line help

---

## Research Integrity Notes

### What This Provides
- Objective behavioral metrics
- Tool-use traces for anti-placebo verification
- Self-modification verification via git diff

### What This Does NOT Provide
- Ground truth for "why" agent did something
- Validation that metrics measure what we think
- Protection against measurement apparatus bugs

### Key Principle
Metrics are operational definitions, not ground truth. A metric means what we measure it to mean, not what we intuitively think it means.
