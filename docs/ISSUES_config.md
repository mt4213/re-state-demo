# ISSUES: env_config.py & .env (Configuration System)

## Bugs

### None Known
No confirmed bugs at this time.

## Design Concerns

### 1. No Generic SYSTEM_PROMPT Variable
**Issue:** Must use `SYSTEM_PROMPT_FULL`, not `SYSTEM_PROMPT`.

**Impact:**
- Confusing for users
- Natural assumption is `SYSTEM_PROMPT=...`
- Easy to misconfigure

**Question:** Should we support generic `SYSTEM_PROMPT` as fallback?

**Location:** `env_config.py` lines 39-52

---

### 2. Empty String Fallback for Missing Prompts
**Issue:** If `SYSTEM_PROMPT_*` not found, returns `""` (empty string).

**Impact:**
- Agent runs with no system prompt
- May behave unexpectedly
- No error or warning

**Question:** Should we require system prompt to be set?

**Location:** `env_config.py` lines 48-50

---

### 3. One-Time Load Only
**Issue:** `.env` only loaded on first import; changes require restart.

**Impact:**
- Cannot change config during session
- Must restart process to pick up changes
- May be confusing during development

**Question:** Should we support config reload?

**Location:** `env_config.py` lines 14-15, 34-36

---

### 4. No Validation of Prompt Condition
**Issue:** Invalid `PROMPT_CONDITION` values accepted silently.

**Impact:**
- `PROMPT_CONDITION=foo` → tries `SYSTEM_PROMPT_FOO` (doesn't exist)
- Returns empty string
- No error message

**Question:** Should we validate against known conditions?

---

### 5. Inline Comment Stripping May Be Too Aggressive
**Issue:** Strips `#` and everything after, even if `#` is in value.

**Impact:**
- `PASSWORD=foo#bar` → `PASSWORD=foo`
- Cannot use `#` in values
- May break URLs or other values

**Question:** Should we only strip `#` at word boundary?

**Location:** `env_config.py` line 32

---

### 6. No Schema or Type Validation
**Issue:** All values are strings; no type checking.

**Impact:**
- `LLM_TEMPERATURE=foo` silently accepted
- `MAX_DEGEN_ABORT_TURNS=abc` causes parse error later
- Errors caught far from source

**Question:** Should we validate value types?

---

### 7. Inconsistent Temperature Defaults
**Issue:** `re_lay.py` has different defaults for `send()` vs `send_stream()`.

**Impact:**
- Hard to predict actual temperature
- Not controlled by `.env` alone
- Confusing behavior

**Question:** Should this be in `.env` with single source of truth?

**Location:** `re_lay.py` lines 149, 297

---

## Potential Improvements

### 1. Generic SYSTEM_PROMPT Support
```python
def get_system_prompt():
    condition = os.getenv("PROMPT_CONDITION", "full")
    var_map = {
        "minimal": "SYSTEM_PROMPT_MINIMAL",
        "empty": "SYSTEM_PROMPT_EMPTY",
        "full": "SYSTEM_PROMPT_FULL",
    }
    var_name = var_map.get(condition, "SYSTEM_PROMPT_FULL")
    # Try generic fallback
    return os.getenv(var_name) or os.getenv("SYSTEM_PROMPT") or ""
```

### 2. Config Validation
```python
def validate_config():
    errors = []
    try:
        temp = float(os.getenv("LLM_TEMPERATURE", "1.0"))
        if not 0 <= temp <= 2:
            errors.append("LLM_TEMPERATURE must be between 0 and 2")
    except ValueError:
        errors.append("LLM_TEMPERATURE must be a number")
    return errors
```

### 3. Config Reload
```python
def reload_env():
    global _loaded
    _loaded = False
    load_env()
```

### 4. Prompt Condition Validation
```python
VALID_CONDITIONS = {"full", "minimal", "empty"}
if condition not in VALID_CONDITIONS:
    logger.warning(f"Invalid PROMPT_CONDITION '{condition}', using 'full'")
    condition = "full"
```

### 5. Better Comment Stripping
```python
# Only strip # if preceded by whitespace
value = value.split("#")[0].strip() if " #" in value else value
```

---

## Questions for Further Investigation

1. **What is the most common PROMPT_CONDITION used?** Do we need all three?

2. **Are users confused by the SYSTEM_PROMPT_FULL naming?** Would SYSTEM_PROMPT be clearer?

3. **How often do configuration errors cause silent failures?**

4. **Should we have a config file validation command?**

5. **Is the .env file the right place for configuration, or should we use a more structured format?**

---

## Edge Cases

### 1. .env File Doesn't Exist
**Behavior:** `load_env()` continues without error.

**Question:** Should we warn if .env not found?

**Location:** `env_config.py` lines 19-24

---

### 2. Empty .env File
**Behavior:** Loads successfully, no env vars set.

**Question:** Is this a valid state?

---

### 3. Duplicate Keys in .env
**Behavior:** Last occurrence wins (standard .env behavior).

**Question:** Should we detect and warn?

---

### 4. Value with Internal # Character
**Behavior:** Everything after # stripped.

**Example:** `URL=http://example.com#anchor` → `URL=http://example.com`

**Location:** `env_config.py` line 32

---

### 5. Very Long Prompt
**Behavior:** Loaded into memory, passed to LLM.

**Question:** Should we validate prompt length?

---

## Performance Considerations

### Load Time
- `.env` loaded at module import
- Synchronous file read
- Negligible for typical .env files (< 1 KB)

### Memory
- All env vars kept in `os.environ`
- No additional memory overhead

### Optimization Opportunities
- Lazy load (only when needed)
- Cache parsed values
- Validate only on demand

---

## Security Considerations

### .env File Permissions
**Issue:** `.env` may contain sensitive keys (API keys, passwords).

**Risk:**
- File may be world-readable
- Logged to version control accidentally
- Included in container images

**Mitigations:**
- Add `.env` to `.gitignore`
- Set restrictive permissions (0600)
- Use secret management for production

### API Key Exposure
**Issue:** `LLM_API_KEY` in .env visible in process listing.

**Mitigation:**
- Use secure credential store
- Pass via stdin or file descriptor
- Rotate keys regularly

---

## Dependencies Status

| Module | Purpose | Required |
|--------|---------|----------|
| `os` | Environment variable access | Yes |

---

## Testing Gaps

### No Unit Tests
- No tests for `load_env()`
- No tests for `get_system_prompt()`
- No tests for prompt condition mapping

### No Integration Tests
- No tests for .env file parsing
- No tests for env var precedence

### Manual Testing Only
- All verification is manual
- No automated regression testing

---

## Documentation Gaps

### Missing
- No explanation of PROMPT_CONDITION system in .env file
- No list of all supported env vars
- No examples of valid .env files

### Present
- Module-level docstring
- Function docstrings
- Inline comments

---

## Configuration Drift

### Problem
Configuration spread across multiple sources:
- `.env` file
- `re_lay.py` constants
- `docker_run.sh` defaults
- Host environment

### Impact
- Hard to know actual configuration
- Changes in one place may not affect others
- Difficult to reproduce runs

### Potential Solution
Single source of truth config file with validation.
