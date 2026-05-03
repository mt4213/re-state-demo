# ISSUES: re_cur.py (Core Agent Loop)

## Bugs

### None Known
No confirmed bugs at this time.

## Design Concerns

### 1. All Exits Are `sys.exit(1)`
**Issue:** Every termination path uses `exit(1)`, including natural completion after 100 turns.

**Impact:**
- Cannot distinguish "agent finished task" from "agent crashed"
- Restart daemon treats all exits as failures
- No way to signal successful completion

**Question:** Should natural completion use `exit(0)`?

**Location:** Lines 293, 326, 332, 411, 455, 462

---

### 2. Circuit Breaker Thresholds Are Hard-Coded
**Issue:** `MAX_NO_TOOL_TURNS = 3`, `MAX_LLM_ERROR_TURNS = 5`, etc. are constants, not configurable.

**Impact:**
- Cannot tune thresholds without editing code
- Different tasks/models may need different tolerances
- Experiments require code changes

**Question:** Should these be environment variables?

**Location:** Lines 65-68, 87-89

---

### 3. Message Eviction May Lose Important Context
**Issue:** Eviction policy is "oldest first," which may delete crucial context.

**Impact:**
- Early instructions or discoveries could be lost
- Agent may "forget" important constraints
- 25k char limit may be too small for complex tasks

**Question:** Should eviction be smarter (e.g., keep system + recent N turns)?

**Location:** Lines 105-118

---

### 4. No Distinction Between "Stuck" and "Thinking"
**Issue:** No-tool counter triggers after 3 turns, but deep reasoning might take longer.

**Impact:**
- Agent genuinely thinking may be killed prematurely
- Forces tool-use even when inappropriate
- May inhibit genuine problem-solving

**Question:** Is 3 turns the right threshold? Should it be time-based instead?

**Location:** Lines 417-455

---

### 5. Error Injection Creates Synthetic History
**Issue:** Parse error handling creates fake tool calls that never happened.

**Impact:**
- Agent learns from fabricated interactions
- May confuse the model about what actually occurred
- Audit log contains synthetic events

**Question:** Is synthetic history better than no history?

**Location:** Lines 296-327

---

### 6. Degeneration Abort Count Never Resets
**Issue:** `degen_abort_count` increments but never resets on successful turns.

**Impact:**
- 3 degeneration aborts over entire session trigger exit
- Even if aborts were hours apart
- May be too strict for long sessions

**Question:** Should this reset after N successful turns?

**Location:** Lines 279, 291-294

---

### 7. Repeated Tool Signature Includes Arguments
**Issue:** Signature comparison includes full argument string, so `file_write({"path": "a.txt"})` and `file_write({"path": "b.txt"})` are different.

**Impact:**
- Agent can loop by changing minor arguments
- May not catch actual repetitive behavior
- Overly specific signature

**Question:** Should signature be tool name only?

**Location:** Lines 406-414

---

### 8. Implicit Memory Re-Sends to LLM
**Issue:** When memory is recalled, the entire message sequence is re-sent to LLM.

**Impact:**
- Doubles token cost for those turns
- May produce different response than original
- Agent sees "second chance" as new turn

**Question:** Should memory be appended to same turn instead?

**Location:** Lines 241-271

---

## Potential Improvements

### 1. Configurable Circuit Breakers
Move thresholds to environment variables:
- `MAX_NO_TOOL_TURNS`
- `MAX_LLM_ERROR_TURNS`
- `MAX_PARSE_ERROR_TURNS`
- `MAX_REPEATED_TOOL_TURNS`
- `MAX_HISTORY_CHARS`

---

### 2. Smarter Message Eviction
Implement eviction strategies:
- Keep system message + recent N turns
- Keep messages containing specific keywords
- Keep tool results, discard agent reasoning

---

### 3. Graceful Exit Codes
- `exit(0)` for natural completion
- `exit(1)` for circuit breaker
- `exit(2)` for unrecoverable error

---

### 4. Degeneration Count Reset
Reset `degen_abort_count` after N successful turns to allow occasional loops.

---

### 5. Tool-Name-Only Signature
Change repeated tool detection to compare tool names only, not arguments.

---

### 6. Memory Injection Timing
Inject recalled memory BEFORE sending to LLM, not after getting response.

---

## Questions for Further Investigation

1. **What is the actual distribution of turn counts in successful runs?** Are 3 turns too few for no-tool detection?

2. **How often does degeneration detection trigger?** Is it catching real loops or false positives?

3. **What is the most common circuit breaker?** Which exit condition dominates?

4. **Is message eviction actually necessary?** What's the typical message count when eviction triggers?

5. **Does error injection actually help recovery?** Or does it just confuse the agent?

6. **Is implicit memory actually being used?** What percentage of sessions trigger recall?

---

## Edge Cases

### 1. Empty System Prompt
If `SYSTEM_PROMPT` is empty, agent starts with no instructions.

**Handled:** Yes, but behavior is undefined.

---

### 2. All Tools Disabled
If `TOOLS = []` in `re_lay.py`, agent can never call tools.

**Handled:** Triggers no-tool breaker immediately.

---

### 3. Crash Context File Exists but is Empty
If `CRASH_CONTEXT_PATH` points to empty file.

**Handled:** `load_episodic_memory()` returns `None` gracefully.

---

### 4. Degeneration Detector Import Fails
If `degeneration.py` is missing.

**Handled:** Sets `DEGENERATION_ENABLED = False`, logs warning.

---

### 5. Recall Module Raises Exception
If `recall_module.recall()` crashes.

**Handled:** Catches exception, logs, skips recall (lines 252-254).

---

## Performance Considerations

### Token Cost
- Each turn sends full message history to LLM
- Implicit memory recall doubles cost for those turns
- No token counting or budgeting

### Disk I/O
- `messages.json` written 2-3 times per turn
- `stream.json` written ~20 times per second
- `sealed_audit.log` appended after tool execution

### Memory
- Entire message history loaded into memory
- No streaming of history (only current LLM response)

---

## Security Considerations

### Tool Execution
- Tools execute via `tools/execute.py`
- No `PROTECTED_PATHS` enforcement (removed in prior commit)
- Agent can modify any file in workspace

### Audit Integrity
- `sealed_audit.log` written to unmounted directory
- Agent cannot tamper with audit trail
- But agent can still modify its own code

---

## Dependencies Status

| Dependency | Status | Notes |
|------------|--------|-------|
| `re_lay` | Required | Core LLM communication |
| `sealed_audit` | Required | Tamper-proof logging |
| `tools.execute` | Required | Tool execution |
| `env_config` | Required | Config loading |
| `memory.recall` | Optional | Implicit memory |
| `degeneration` | Optional | Loop detection |
| `re_scribe` | Optional | Crash compression |

---

## Testing Gaps

### No Unit Tests
- No tests for individual functions
- No tests for circuit breaker logic
- No tests for message eviction

### No Integration Tests
- No tests for full agent loop
- No tests for crash recovery
- No tests for implicit memory

### Manual Testing Only
- All verification is manual
- No automated regression testing

---

## Documentation Gaps

### Missing
- No docstrings for most functions
- No inline comments for complex logic
- No examples of message structure

### Present
- Module-level docstring
- Some logging messages
- This audit document
