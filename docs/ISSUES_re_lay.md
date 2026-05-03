# ISSUES: re_lay.py (LLM Router)

## Bugs

### 1. Temperature Default Inconsistency
**Issue:** `send_stream()` defaults temperature to `1.0`, but `send()` defaults to `1.05`.

**Impact:**
- Inconsistent behavior between streaming and non-streaming modes
- Hard to reason about actual temperature being used

**Fix:** Use same default for both functions.

**Location:** Lines 149, 297

---

### 2. Empty User Message May Confuse Models
**Issue:** When no user message exists, `{"role": "user", "content": ""}` is added.

**Impact:**
- Some models may treat empty user message as signal
- Not documented in API contracts
- May influence generation unexpectedly

**Question:** Should this be a "." or "[No user query]" instead?

**Location:** Lines 143, 291

---

## Design Concerns

### 1. No Retry Logic
**Issue:** Failed requests are not retried.

**Impact:**
- Transient network failures cause immediate errors
- No resilience against temporary server issues
- Circuit breaker may trigger unnecessarily

**Question:** Should failed requests be retried with exponential backoff?

**Location:** Entire file (no retry logic exists)

---

### 2. No Connection Pooling
**Issue:** Each request creates a new HTTP connection.

**Impact:**
- Slower requests due to TCP handshake overhead
- Higher server load
- No keep-alive benefit

**Question:** Is connection pooling necessary for local llama.cpp?

---

### 3. Message Copy on Every Request
**Issue:** `copy.deepcopy(messages)` on every request.

**Impact:**
- Unnecessary memory allocation
- Slower for long conversation histories
- Messages are never modified in-place anyway

**Question:** Can we avoid copying if we don't modify messages?

**Location:** Lines 112, 261

---

### 4. Tool Definitions Hard-Coded
**Issue:** `TOOLS` constant is defined in `re_lay.py`, not configurable.

**Impact:**
- Cannot add/remove tools without editing code
- Agent cannot discover new tools at runtime
- Tight coupling between router and tools

**Question:** Should tools be loaded from config file?

**Location:** Lines 20-88

---

### 5. Abort Event Only Works with Streaming
**Issue:** `abort_event` parameter only exists in `send_stream()`, not `send()`.

**Impact:**
- Degeneration detection only works with streaming mode
- `re_cur.py` always uses streaming, so this is OK
- But API is inconsistent

**Question:** Should `send()` also accept `abort_event`?

**Location:** Line 101, 243

---

### 6. No Request/Response Logging
**Issue:** Failed requests log errors, but successful requests are not logged.

**Impact:**
- Hard to debug issues
- No visibility into what's being sent to LLM
- Cannot trace token usage

**Question:** Should successful requests be logged at DEBUG level?

---

### 7. Silent JSON Decode Error Handling
**Issue:** Malformed SSE chunks are silently ignored (lines 220-221).

**Impact:**
- May hide real problems
- No way to know if streaming is corrupted
- Could accumulate partial responses

**Question:** Should malformed chunks be logged?

**Location:** Lines 220-221

---

### 8. Hard-Coded 500 Char Error Truncation
**Issue:** HTTP error bodies truncated to 500 chars.

**Impact:**
- May lose important error details
- Hard to debug complex failures

**Question:** Is 500 chars enough? Should this be configurable?

**Location:** Lines 233, 322

---

## Potential Improvements

### 1. Retry Logic with Exponential Backoff
```python
max_retries = 3
for attempt in range(max_retries):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if attempt < max_retries - 1 and e.code >= 500:
            time.sleep(2 ** attempt)
            continue
        raise
```

---

### 2. Connection Pooling
Use `urllib3.PoolManager` or similar for connection reuse.

---

### 3. Request Logging
```python
logger.debug("LLM request: model=%s, messages=%d, max_tokens=%d",
             model, len(messages), max_tokens)
logger.debug("LLM response: content_len=%d, tool_calls=%d",
             len(content) or 0, len(tool_calls) or 0)
```

---

### 4. Configurable Tools
Load tools from YAML/JSON file instead of hard-coded constant.

---

### 5. Response Validation
Validate response structure before returning:
- Check `choices` array exists
- Check `message` object exists
- Check `content` is string

---

### 6. Token Usage Tracking
Return `usage` field from response (tokens consumed).

---

### 7. Streaming Callback Error Handling
If `on_chunk` raises exception, catch and handle gracefully.

---

## Questions for Further Investigation

1. **What is the actual failure rate of LLM requests?** Is retry logic necessary?

2. **How often does the empty user message cause issues?** Have we observed any model confusion?

3. **Is message copying actually a performance bottleneck?** Profile before optimizing.

4. **Should tools be dynamically loaded?** What would that look like?

5. **Is streaming necessary for every request?** Could we use non-streaming for simple queries?

---

## Edge Cases

### 1. Empty Messages Array
**Behavior:** Would add empty user message, but original content is lost.

**Question:** Should this be rejected as invalid input?

---

### 2. All Messages Filtered Out
**Behavior:** After preprocessing, if all messages are removed, we'd have empty array + user message.

**Question:** Is this a valid state?

---

### 3. Tool Call with No Arguments
**Behavior:** `arguments` would be empty string or `"{}"`.

**Handled:** `json.loads("{}")` returns empty dict, no error.

---

### 4. Abort Event Set Before Request
**Behavior:** Request would be sent, then immediately aborted.

**Question:** Should we check abort_event before sending request?

---

### 5. Zero Max Tokens
**Behavior:** LLM would return immediately with empty response.

**Question:** Should this be validated and rejected?

---

## Performance Considerations

### Current Bottlenecks
- Message copying on every request
- No connection pooling
- No request batching

### Optimization Opportunities
- Avoid copying if messages not modified
- Reuse HTTP connections
- Batch multiple requests (if LLM supports)

---

## Security Considerations

### No Input Validation
- Tool parameters are not validated
- File paths can point anywhere
- Commands are executed as-is

**Mitigation:** `tools/execute.py` should enforce security (but currently has no PROTECTED_PATHS).

---

### API Key in Environment
- `LLM_API_KEY` is read from environment
- May be visible in process listing
- Should use secure credential store

---

## Dependencies Status

| Dependency | Status | Notes |
|------------|--------|-------|
| `env_config` | Required | Load .env before os.getenv() |
| `urllib` | Required | HTTP requests (stdlib) |
| `json` | Required | Payload/response parsing |
| `copy` | Required | Message copying |
| `threading` | Optional | For abort_event type hint only |

---

## Testing Gaps

### No Unit Tests
- No tests for message preprocessing
- No tests for tool call assembly
- No tests for error handling

### No Integration Tests
- No tests against real LLM server
- No tests for streaming behavior
- No tests for abort handling

### Manual Testing Only
- All verification is manual
- No automated regression testing

---

## Documentation Gaps

### Missing
- No docstrings for `send_stream()` or `send()`
- No explanation of Qwen3 quirk in code
- No examples of tool call format

### Present
- Module-level docstring
- Some inline comments
- Tool descriptions in `TOOLS` constant
