# AUDIT: re_cur.py (Core Agent Loop)

## Purpose

`re_cur.py` is the core ContReAct (Continuous Reasoning + Acting) loop. It orchestrates:
- Conversation with LLM via `re_lay.py`
- Tool execution via `tools/execute.py`
- State persistence via `messages.json`
- Audit logging via `sealed_audit.py`
- Degeneration detection via `degeneration.py`
- Episodic memory loading from crash recovery

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    MAIN LOOP (turns 1→100)                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. EVICT old messages if > 25k chars                        │
│  2. CALL LLM with streaming + degeneration detection         │
│  3. OPTIONAL: recall implicit memory if keywords hit         │
│  4. HANDLE response (errors, tool calls, or text-only)       │
│  5. EXECUTE tools and append results                         │
│  6. PERSIST state and audit log                              │
│  7. CHECK circuit breakers → exit if triggered               │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Constants & Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_ITERATIONS` | 100 | Hard limit on total turns |
| `MAX_NO_TOOL_TURNS` | 3 | Consecutive turns without tools before exit |
| `MAX_LLM_ERROR_TURNS` | 5 | Consecutive LLM API failures before exit |
| `MAX_PARSE_ERROR_TURNS` | 5 | Consecutive JSON parse errors before exit |
| `MAX_DEGEN_ABORT_TURNS` | 3 (env var) | Consecutive degeneration aborts before exit |
| `MAX_REPEATED_TOOL_TURNS` | 4 | Consecutive identical tool signatures before exit |
| `MAX_HISTORY_CHARS` | 25000 | Context window limit for message eviction |

## Circuit Breakers

### 1. No-Tool Breaker (`MAX_NO_TOOL_TURNS = 3`)
**Triggers when:** Agent produces text-only responses (no tool calls) for 3 consecutive turns.

**Behavior:**
- Injects error message via `ERROR_INJECT_ROLE` (default: "tool")
- Exits with `sys.exit(1)`

**Error injection modes:**
- `system` → system message with error
- `tool` → synthetic tool call + tool result error
- `user` → user message with error

**Location:** Lines 417-455

### 2. LLM Error Breaker (`MAX_LLM_ERROR_TURNS = 5`)
**Triggers when:** LLM API returns errors (HTTP failures, timeouts) for 5 consecutive turns.

**Behavior:**
- Logs error
- Sleeps with exponential backoff (`2 * error_count` seconds)
- Exits with `sys.exit(1)` after 5 failures

**Location:** Lines 328-335

### 3. Parse Error Breaker (`MAX_PARSE_ERROR_TURNS = 5`)
**Triggers when:** JSON parsing fails (truncated response, malformed tool call) for 5 consecutive turns.

**Behavior:**
- Synthesizes a fake tool call result with error message
- Lets agent see concrete error instead of regenerating blindly
- Exits with `sys.exit(1)` after 5 failures

**Location:** Lines 296-327

### 4. Degeneration Abort Breaker (`MAX_DEGEN_ABORT_TURNS = 3`)
**Triggers when:** Degeneration detector flags reasoning as looping (low velocity, high similarity) for 3 consecutive turns.

**Behavior:**
- Injects system message: "[Error: Reasoning entered a degenerate loop. Try a different approach.]"
- Exits with `sys.exit(1)` after 3 aborts

**Location:** Lines 277-294

### 5. Repeated Tool Breaker (`MAX_REPEATED_TOOL_TURNS = 4`)
**Triggers when:** Agent executes identical tool signature (name + arguments) for 4 consecutive turns.

**Behavior:**
- Logs detection
- Exits immediately with `sys.exit(1)`

**Signature format:** `tuple([(tool_name, args_str), ...])`

**Location:** Lines 406-414

## Message Structure

### Core Fields
```python
{
    "role": "system" | "assistant" | "tool" | AGENT_ROLE,
    "content": str | None,
    "tool_calls": [{...}] | None,
    "timestamp": "2026-05-03T21:30:42+02:00"
}
```

### Agent Message Extensions
```python
{
    "role": AGENT_ROLE,  # "assistant" by default, configurable via AGENT_ROLE_NAME
    "content": str | None,
    "tool_calls": [{...}] | None,
    "reasoning": str,  # Qwen3 thinking mode output
    "timestamp": "...",
    "_thought": str  # Internal metadata trace
}
```

### Tool Result Message
```python
{
    "role": "tool",
    "tool_call_id": str,  # Matches tool_call.id from agent message
    "content": str,  # Tool output
    "timestamp": "..."
}
```

## State Persistence

### Files
- **`state/messages.json`** — Full conversation history (persisted each turn)
- **`state/stream.json`** — Live streaming buffer (~20 writes/sec)

### Write Triggers
1. After LLM response (before tool execution)
2. After tool execution
3. On error injection

### Audit Logging
- **`sealed_audit.write_sealed_record()`** called after tool execution
- Writes to `eval_results/chats/sealed_audit_*.jsonl`
- Directory is NOT mounted in Docker container (tamper-proof)

## Degeneration Detection

### Integration
- **Module:** `degeneration.DegenerationDetector`
- **Optional:** Only active if module can be imported

### Detection Flow
1. Detector reset at start of each turn
2. Streaming callback passes reasoning tokens (delta only) to detector
3. Detector analyzes: token velocity, self-similarity, stall duration
4. If flagged: `abort_event.set()` → streaming loop aborts early
5. Response marked with `error: "degeneration_abort"`

### Configurable via Environment
- `MAX_DEGEN_ABORT_TURNS` — Default: 3

## Episodic Memory (Crash Recovery)

### Loading on Startup
1. Checks `CRASH_CONTEXT_PATH` environment variable
2. If file exists: reads crash context
3. Passes through `re_scribe.compress()` to create narrative summary
4. Injects as system message: `[Episodic memory from previous session] {summary}`

### Module: `re_scribe.py`
- **Function:** `compress(raw_text)` → short first-person narrative
- **Purpose:** Condense crash context into usable memory

### Dependencies
- Restart daemon must set `CRASH_CONTEXT_PATH` env var
- `re_scribe.py` must be importable

## Implicit Memory Recall

### Trigger Conditions (ALL must be true)
1. `recall_module` import succeeds (`memory/recall.py`)
2. `IMPLICIT_MEMORY_ENABLED == "1"` (env var)
3. `recall_count < MAX_RECALL_PER_SESSION` (budget)
4. LLM response contains `reasoning`
5. `recall_module.should_recall(reasoning)` returns True (keyword match)

### Behavior
1. Calls `recall_module.recall(reasoning)` → relevant memory chunks
2. Injects as system message
3. Resets degeneration detector
4. **Re-sends to LLM** with memory injected (get fresh response)

### Budget
- `MAX_RECALL_PER_SESSION` — Defined in `memory/recall.py`
- Counter resets each session (not persisted)

## Message Eviction

### Trigger
- When `estimate_chars(messages) > 25000` AND `len(messages) > 4`

### Policy
1. Preserves first message if it's `role: "system"`
2. Finds oldest `AGENT_ROLE` message
3. Evicts that message + all following `tool` messages
4. Stops when next `AGENT_ROLE` message is found
5. Logs eviction count and indices

### Function
- **`evict_oldest(messages)`** — Returns `True` if eviction occurred, `False` if nothing to evict

## Error Injection

### Purpose
When agent produces text-only response (no tool calls), inject error to prompt recovery.

### Modes (via `ERROR_INJECT_ROLE` env var)

| Mode | Message Structure | Use Case |
|------|-------------------|----------|
| `system` | `{"role": "system", "content": "[Error: No valid tool call detected.]"}` | Treat as system-level failure |
| `tool` | Agent message with fake tool call → Tool result error | Simulate failed tool execution |
| `user` | `{"role": "user", "content": "[Error: No valid tool call detected.]"}` | Treat as user correction |

**Default:** `tool` (synthetic tool call)

## Exit Conditions

All exits use `sys.exit(1)` except:
- Natural loop completion after `MAX_ITERATIONS` → also `sys.exit(1)`

### Exit Reasons
1. Circuit breaker triggered (all 5 breakers)
2. Natural completion (100 turns reached)

**Note:** There is no "successful" exit code (0). All terminations are `exit(1)`.

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECUR_LOG_LEVEL` | INFO | Logging verbosity |
| `ERROR_INJECT_ROLE` | tool | Error injection mode for no-tool turns |
| `AGENT_ROLE_NAME` | assistant | Role label for agent messages |
| `IMPLICIT_MEMORY_ENABLED` | 0 | Enable implicit memory recall |
| `MAX_DEGEN_ABORT_TURNS` | 3 | Degeneration abort tolerance |
| `CRASH_CONTEXT_PATH` | - | Path to crash context file (set by daemon) |

### System Prompt
- Loaded via `env_config.get_system_prompt()`
- Maps to `SYSTEM_PROMPT_*` variables based on `PROMPT_CONDITION`

## Dependencies

| Module | Purpose | Optional |
|--------|---------|----------|
| `re_lay` | LLM communication | No |
| `sealed_audit` | Tamper-proof logging | No |
| `tools.execute` | Tool execution | No |
| `env_config` | Config loading | No |
| `memory.recall` | Implicit memory | Yes |
| `degeneration` | Loop detection | Yes |
| `re_scribe` | Crash compression | Yes (crash recovery only) |

## Data Flow

```
┌──────────────┐
│ Load config  │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│ Initialize state │  messages.json (read)
└──────┬───────────┘
       │
       ▼
┌───────────────────────────────┐
│ Load episodic memory if crash │  CRASH_CONTEXT_PATH (env)
└──────┬────────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ Main loop (100 turns max)  │
└─────────────────────────────┘
       │
       ├─▶ Evict old messages if > 25k chars
       │
       ├─▶ Send to LLM (streaming + degen detection)
       │
       ├─▶ Optional: Recall implicit memory
       │       └─▶ Re-send to LLM with memory
       │
       ├─▶ Check response.error
       │       ├─▶ degeneration_abort → count → exit if >= 3
       │       ├─▶ parse_error → synthesize → count → exit if >= 5
       │       └─▶ other error → count → exit if >= 5
       │
       ├─▶ Build agent message (content + reasoning + tool_calls)
       │
       ├─▶ If tool_calls:
       │       ├─▶ Execute each tool
       │       ├─▶ Append results
       │       ├─▶ Check repeated tool signature → exit if >= 4
       │       └─▶ Reset no_tool_count
       │
       ├─▶ If no tool_calls:
       │       ├─▶ Inject error (per ERROR_INJECT_ROLE)
       │       ├─▶ Increment no_tool_count → exit if >= 3
       │
       ├─▶ Persist to messages.json
       │
       └─▶ Write to sealed_audit.log
```

## Logging

### Loggers
- **`re_cur`** — Main loop events (INFO level)
- **`re_cur.signal`** — Clean signal output for UI (`>>` prefix)

### Signals
- `>> [THINK]` — Agent reasoning or content
- `>> [ACT]` — Tool execution
- `>> [OBS]` — Tool result

## Known Quirks

1. **No successful exit code** — All exits are `sys.exit(1)`, even natural completion
2. **Empty user message** — `re_lay.py` adds empty user message for Jinja compatibility
3. **Thought parameter stripping** — Tool call "thought" parameter is removed before sending to LLM to save context
4. **Agent role flexibility** — `AGENT_ROLE` can be "entity", "self", "actor" for experimentation
