# AUDIT: re_lay.py (LLM Router)

## Purpose

`re_lay.py` handles communication with LLM servers (llama.cpp, vLLM, OpenAI-compatible APIs). It provides:
- Streaming and non-streaming request functions
- Tool definition in OpenAI function-calling format
- Message preprocessing for Qwen3 thinking mode compatibility
- Error handling and response parsing

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         re_lay.py                            │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  TOOLS (constant) ──▶ send_stream() ──▶ send()              │
│                        │                  │                  │
│                        ▼                  ▼                  │
│               clean_messages()    clean_messages()           │
│                        │                  │                  │
│                        ▼                  ▼                  │
│              urllib.request     urllib.request              │
│               (streaming)        (non-streaming)             │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Constants

| Constant | Default | Purpose |
|----------|---------|---------|
| `DEFAULT_BASE_URL` | `http://127.0.0.1:18000` | LLM server endpoint |
| `DEFAULT_MAX_TOKENS` | 10 | Max tokens to generate |
| `DEFAULT_TIMEOUT` | 120 | Request timeout in seconds |

## Tool Definitions

The `TOOLS` constant defines 3 tools in OpenAI function-calling format:

### 1. `terminal`
**Description:** Execute a shell command. Returns stdout and stderr.

**Parameters:**
- `thought` (required): Brief reason for action (under 20 words)
- `command` (required): The bash command to execute

### 2. `file_read`
**Description:** Read the contents of a file.

**Parameters:**
- `thought` (required): Brief reason for action
- `path` (required): Absolute path to the file

### 3. `file_write`
**Description:** Write content to a file. Creates or overwrites.

**Parameters:**
- `thought` (required): Brief reason for action
- `path` (required): Absolute path to the file
- `content` (required): The content to write

**Note:** The `thought` parameter is stripped from arguments before sending to LLM to save context.

## Functions

### `send_stream(messages, on_chunk, base_url, max_tokens, timeout, tools, abort_event)`

**Purpose:** Send messages to LLM with streaming response.

**Returns:** Dictionary with keys:
- `content`: str or None (text response)
- `tool_calls`: list of tool call dicts, or None
- `reasoning`: str or None (Qwen3 thinking mode output)
- `error`: str if request failed

**Streaming callback:** `on_chunk(content, tool_calls, reasoning)` called on each SSE chunk.

**Abort handling:** If `abort_event` is set during streaming, returns early with `error: "degeneration_abort"`.

**Location:** Lines 91-240

---

### `send(messages, base_url, max_tokens, timeout, tools)`

**Purpose:** Send messages to LLM without streaming (simpler, non-async).

**Returns:** Same dictionary format as `send_stream()`, but no `reasoning` key.

**Location:** Lines 243-342

---

## Message Preprocessing (Qwen3 Quirk)

### Problem
Qwen3 with `enable_thinking` rejects assistant message prefill with error:
> "Assistant response prefill is incompatible with enable_thinking"

### Solution: `clean_messages`
Both `send_stream()` and `send()` process messages before sending:

1. **Strip assistant/self/entity messages entirely**
   - Sending empty assistant (no content/tool_calls) causes API error
   - Content was stripped to avoid Qwen3 thinking mode prefill errors

2. **Keep system messages** (only if non-empty)

3. **Keep tool results** (essential for conversation continuity)

4. **Keep user messages**

5. **Remove empty system messages**

6. **Guarantee at least one user message**
   - If no user message exists, append `{"role": "user", "content": ""}`
   - Empty string preferred over "." to reduce influence on generation
   - Required for Jinja template compatibility

**Location:** Lines 110-143 (streaming), Lines 258-291 (non-streaming)

### Why Empty User Message?
- vLLM Jinja template raises "No user query found" if no user message exists
- Empty string satisfies template without influencing generation
- Better than "." which may be treated as actual input

## Request Format

### Endpoint
```
{base_url}/v1/chat/completions
```

### Payload
```json
{
  "model": "{LLM_MODEL}",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "tool", "tool_call_id": "...", "content": "..."}
  ],
  "max_tokens": 500,
  "temperature": 1.1,
  "stream": true,
  "tools": [...]
}
```

### Headers
```
Content-Type: application/json
Authorization: Bearer {LLM_API_KEY}  # if set and not "dummy"
```

## Streaming Response Parsing

### SSE Format
```
data: {"choices":[{"delta":{"content":"..."}}]}
data: {"choices":[{"delta":{"reasoning_content":"..."}}]}
data: {"choices":[{"delta":{"tool_calls":[...]}}
data: [DONE]
```

### Accumulation
- `content`: Concatenated from `delta.content`
- `reasoning`: Concatenated from `delta.reasoning_content`
- `tool_calls`: Assembled from `delta.tool_calls` array

**Tool call assembly:** Uses index-based accumulation to handle streaming fragments.

**Location:** Lines 174-221

## Error Handling

### HTTP Errors
Returns response with `error: "HTTP {code}: {body}"`

**Errors caught:**
- HTTP 4xx/5xx responses
- Connection failures
- Timeout errors

### JSON Decode Errors
Silently ignored (lines 220-221) — handles malformed SSE chunks.

### Unexpected Response Structure
Returns `error: "Bad response: {e}"` if choices array is missing/malformed.

**Location:** Lines 230-241, 316-342

## Abort Handling (Streaming)

### Degeneration Abort
If `abort_event.is_set()` during streaming:
1. Stops reading from SSE stream
2. Returns response with:
   - `error: "degeneration_abort"`
   - `reason: "Token velocity stall / degenerate loop detected"`

**Location:** Lines 175-184

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_BASE_URL` | `http://127.0.0.1:18000` | API endpoint |
| `LLM_MODEL` | `local` | Model name |
| `LLM_MAX_TOKENS` | 10 | Max generation tokens |
| `LLM_TIMEOUT` | 120 | Request timeout (seconds) |
| `LLM_TEMPERATURE` | 1.0 (send) / 1.05 (send_stream) | Sampling temperature |
| `LLM_API_KEY` | - | API key (if required) |

### Note on Temperature Inconsistency
- `send_stream()`: defaults to `os.getenv("LLM_TEMPERATURE", "1.0")`
- `send()`: defaults to `os.getenv("LLM_TEMPERATURE", "1.05")`

**Location:** Lines 149, 297

This is likely a bug — should be consistent.

## Dependencies

| Module | Purpose |
|--------|---------|
| `env_config` | Load .env before module-level os.getenv() |
| `urllib` | HTTP requests (stdlib) |
| `json` | Payload/response parsing |
| `copy` | Deepcopy messages before preprocessing |
| `threading` | For abort_event type hint |

## Data Flow

```
messages[] → clean_messages() → payload → urllib.request
                                                   │
                                                   ▼
                                      SSE stream (if streaming)
                                                   │
                                                   ▼
                                      on_chunk(content, tool_calls, reasoning)
                                                   │
                                                   ▼
                                      return {content, tool_calls, reasoning, error}
```

## Throttling

### Stream Write Throttling
Stream writes are throttled to ~20 writes/sec via `_last_stream_write` global.

**Note:** This is actually in `re_cur.py`, not `re_lay.py`. `re_lay.py` has no throttling — it calls `on_chunk` immediately for each SSE chunk.

**Location:** `re_cur.py` lines 72-83

## Tool Call Processing

### In `re_cur.py` (not `re_lay.py`)
After `send_stream()` returns, `re_cur.py` processes tool calls:

1. Extract `thought` parameter from arguments
2. Strip `thought` from arguments (to save context)
3. Log via `_signal.info("[ACT] ...")`
4. Execute via `tools.execute.execute()`
5. Append result to messages

**Location:** `re_cur.py` lines 375-402

## Known Quirks

1. **Empty user message** — Added if no user message exists (Jinja compatibility)
2. **Assistant messages stripped** — Qwen3 thinking mode incompatibility
3. **Thought parameter stripped** — Context optimization, not LLM requirement
4. **Temperature inconsistency** — `send_stream` vs `send` have different defaults
5. **No retry logic** — Failed requests are not retried
6. **Streaming-only abort** — `abort_event` only works with `send_stream()`

## Security

### API Key Handling
- `LLM_API_KEY` is read from environment
- If set and not "dummy", added as `Authorization: Bearer {key}` header
- Key is sent over HTTPS if `base_url` uses https://

### No Input Sanitization
- Tool parameters are not validated
- File paths are not checked
- Commands are executed as-is by `tools.execute`

## Performance

### Memory
- Entire message history copied via `copy.deepcopy()` before preprocessing
- Accumulated response stored in memory during streaming

### Network
- No connection pooling
- No keep-alive
- Each request creates new HTTP connection

### Latency
- Timeout defaults to 120 seconds
- No progress indication during long requests
