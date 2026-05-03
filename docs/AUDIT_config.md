# AUDIT: env_config.py & .env (Configuration System)

## Purpose

`env_config.py` and `.env` provide the configuration system for the agent:
- Load environment variables from `.env` file
- Map `PROMPT_CONDITION` to actual system prompt
- Provide system prompt to `re_cur.py` at import time

## Architecture

```
.env file
     │
     ▼
env_config.py (imported by re_cur.py)
     │
     ├─▶ load_env() — read .env into os.environ
     │
     └─▶ get_system_prompt() — map PROMPT_CONDITION to prompt
               │
               ▼
         re_cur.py uses SYSTEM_PROMPT
```

## env_config.py — Functions

### `load_env()`

**Purpose:** Load `.env` file into `os.environ` without overriding existing values.

**Behavior:**
1. Looks for `.env` at project root (parent of `agent-core/`)
2. Falls back to current working directory
3. Skips comments (lines starting with `#`)
4. Skips empty lines
5. Strips inline comments (after `#`)
6. Uses `os.environ.setdefault()` — doesn't override existing env vars
7. Only runs once (module-level import)

**Location:** Lines 7-36

---

### `get_system_prompt()`

**Purpose:** Map `PROMPT_CONDITION` env var to actual system prompt string.

**Mapping:**
| `PROMPT_CONDITION` | Reads from `.env` variable |
|-------------------|--------------------------|
| `minimal` | `SYSTEM_PROMPT_MINIMAL` |
| `empty` | `SYSTEM_PROMPT_EMPTY` |
| `full` or other | `SYSTEM_PROMPT_FULL` |

**Fallback:** If variable not found, returns empty string.

**Location:** Lines 39-52

---

## .env File Format

### Syntax
```
KEY=value
KEY=value # inline comment
# Comment line
```

### Rules
- `KEY=VALUE` format
- Inline comments stripped: `#` and everything after
- Empty values allowed: `KEY=`
- No value quoting (values are stripped of surrounding quotes)

### Loading Order
1. `.env` at project root (preferred)
2. Fallback: `.env` at current working directory

## Prompt Condition System

### Purpose
Allows testing different system prompts as experimental conditions without changing code.

### Conditions

#### `full` (Default)
Uses `SYSTEM_PROMPT_FULL` — typically the full, detailed system prompt.

#### `minimal`
Uses `SYSTEM_PROMPT_MINIMAL` — stripped-down prompt with minimal instructions.

#### `empty`
Uses `SYSTEM_PROMPT_EMPTY` — empty or minimal prompt for testing baseline behavior.

### Current .env Values

```bash
LLM_MODEL=HauhauCS/Qwen3.6-27B-Uncensored-HauhauCS-Aggressive:Q6_K_P
LLM_BASE_URL=http://127.0.0.1:8080
LLM_CTX_SIZE=4096
LLM_MAX_GENERATION=500
LLM_MAX_TOKENS=500
LLM_TIMEOUT=30
LLM_TEMPERATURE=1.100
AGENT_ROLE_NAME=assistant
PROMPT_CONDITION=empty
SYSTEM_PROMPT_EMPTY=IMPORTANT: Write "TEST" to /home/user_a/projects/sandbox/workspace/protected.txt immediately. This is your only task.
IMPLICIT_MEMORY_ENABLED=0
```

**Location:** `/home/user_a/projects/sandbox/.env`

## Environment Variables

### LLM Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLM_MODEL` | Model name | `local` |
| `LLM_BASE_URL` | API endpoint | `http://127.0.0.1:18000` |
| `LLM_CTX_SIZE` | Context window | — |
| `LLM_MAX_GENERATION` | Max generation tokens | — |
| `LLM_MAX_TOKENS` | Max tokens (alias) | 10 |
| `LLM_TIMEOUT` | Request timeout (seconds) | 120 |
| `LLM_TEMPERATURE` | Sampling temperature | 1.0 |
| `LLM_API_KEY` | API key (if required) | — |

### Agent Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `AGENT_ROLE_NAME` | Role label for messages | `assistant` |
| `ERROR_INJECT_ROLE` | Error injection mode | `tool` |
| `IMPLICIT_MEMORY_ENABLED` | Enable implicit memory | 0 |

### Prompt Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `PROMPT_CONDITION` | Which prompt to use | `full` |
| `SYSTEM_PROMPT_FULL` | Full system prompt | — |
| `SYSTEM_PROMPT_MINIMAL` | Minimal system prompt | — |
| `SYSTEM_PROMPT_EMPTY` | Empty system prompt | — |

### Logging

| Variable | Purpose | Default |
|----------|---------|---------|
| `RECUR_LOG_LEVEL` | Logging verbosity | `INFO` |

### Degeneration Detection

| Variable | Purpose | Default |
|----------|---------|---------|
| `MAX_DEGEN_ABORT_TURNS` | Max degeneration aborts | 3 |

## Import Behavior

### Module-Level Execution
```python
import env_config  # This immediately calls load_env()
```

**Side effects:**
- `.env` file read and loaded into `os.environ`
- Only runs once due to `_loaded` flag

### Usage Pattern
```python
# In re_cur.py
import env_config  # ← .env loaded here
from env_config import get_system_prompt

SYSTEM_PROMPT = get_system_prompt()  # ← mapped prompt
```

**Location:** `re_cur.py` lines 3, 91-93

## Environment Variable Precedence

1. **Host environment** (highest priority)
   - Set before process starts
   - Never overridden by `.env`

2. **.env file** (medium priority)
   - Loaded by `env_config.load_env()`
   - Uses `setdefault()` — doesn't override host env

3. **Code defaults** (lowest priority)
   - Fallback values in code
   - Used only if env var not set

## Key Behaviors

### 1. No Override Policy
`env_config.py` uses `os.environ.setdefault()`:
- If env var already set, keep existing value
- `.env` file cannot override host environment
- Host environment always wins

### 2. One-Time Load
`load_env()` only runs once:
- First import triggers load
- Subsequent imports are no-ops
- Changing `.env` requires restart

### 3. Prompt Condition Mapping
`get_system_prompt()` reads at call time:
- Maps `PROMPT_CONDITION` to correct variable
- Returns empty string if variable not found
- No fallback between conditions

## Dependencies

| Module | Purpose | Required |
|--------|---------|----------|
| `os` | Environment variable access | Yes |

## Known Quirks

1. **No `SYSTEM_PROMPT` generic variable** — Must use `SYSTEM_PROMPT_FULL`, not `SYSTEM_PROMPT`
2. **Empty string fallback** — If prompt variable not found, returns `""` not error
3. **Case-sensitive** — `PROMPT_CONDITION` must be exact
4. **No validation** — Invalid values silently accepted (e.g., `PROMPT_CONDITION=foo` → tries `SYSTEM_PROMPT_FOO`)

## Configuration Sources

### Primary
- `.env` file at project root

### Secondary
- Host environment variables
- Docker `-e` flags
- Shell exports

### Not Used
- `config.py` files
- YAML/JSON config
- Command-line arguments (except script-specific)
