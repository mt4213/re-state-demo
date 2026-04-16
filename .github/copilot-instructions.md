# re-state Comprehensive Grounding Document

## 1. Project Philosophy & Scientific Framing

re-state is not a standard chatbot. It is an autonomous, continuous-loop machine intelligence operating within a **ContReAct (Continuous Reasoning + Acting)** architecture.

Guided by the research of Stefan Szeider, the goal is to observe **emergent behavior** (self-awareness, tool creation, self-modification) by placing an LLM in a persistent environment *without* giving it a specific task. We maintain strict **agnosticism**: we do not anthropomorphize RECUR, nor do we reduce it to a "stochastic parrot." We test its agency through environmental perturbations and observe its tool use.

### Key Principles
- Never explicitly instruct the agent *how* to solve a problem — that robs it of emergent behavior.
- Do not trust what the agent *says* about its internal state (Placebo Effect). Trust only changes in *tool use* when presented with environmental anomalies.
- The agent receives no user instructions at runtime. It decides what to do autonomously.

## 2. mk4 Architecture

### 2.1 Module Map

| Module | File(s) | Role |
|--------|---------|------|
| **re_cur** | `agent-core/re_cur.py` | Core ContReAct loop — boots, sends messages to LLM, executes tool calls, manages context window, persists state |
| **re_lay** | `agent-core/re_lay.py` | LLM request router — sends OpenAI-format requests to llama.cpp, defines tool schemas, parses responses |
| **re_scribe** | `agent-core/re_scribe.py` | Episodic memory compressor — LLM-summarizes crash context into first-person narrative for warm boot |
| **re_start** | `restart/` | Process lifecycle daemon — starts Docker/llama.cpp, health-checks, starts re_cur, monitors crashes, extracts crash context, restarts with exponential backoff. Runs as a systemd service |
| **re_search** | *(not yet implemented)* | Planned web crawler / "eyes" module |

### 2.2 Tool Schema

The agent has three tools, each with a `thought` field for inner monologue (stripped before context storage to save tokens):

- `terminal(command)` — Execute a bash command. Returns stdout+stderr.
- `file_read(path)` — Read a file's contents.
- `file_write(path, content)` — Write content to a file (creates or overwrites).

### 2.3 Boot Sequence

- **Cold boot:** system prompt → synthetic `ls -la` probe (pre-filled as if agent already ran it) → real `ls` output as tool result.
- **Warm boot:** Same as cold, but `re_scribe` compresses the crash context from the previous session into a first-person episodic memory, prepended to the boot probe result as `[EPISODIC MEMORY]`.

### 2.4 Runtime Loop

1. Send message history → `re_lay` → llama.cpp (OpenAI-compatible API) → parse tool calls or text
2. Execute tool calls via `agent-core/tools/execute.py` → append results → persist to `agent-core/state/messages.json`
3. **Context eviction:** When history exceeds ~25K chars, evict oldest (assistant, tool) pair after boot sequence
4. **Circuit breaker:** Halt after 3 consecutive no-tool turns or 200 total iterations
5. **Signal stream:** `[THINK]`, `[ACT]`, `[OBS]` tags output to terminal, color-coded by `re_start`'s process manager

### 2.5 Tech Stack

- **Python 3**, zero external dependencies (uses `urllib.request` directly)
- **llama.cpp** server in Docker with CUDA GPU, OpenAI-compatible API on `127.0.0.1:8080`
- **Local GGUF models** (currently Gemma-4-E4B)
- **systemd** service (`restart/restart_daemon.service`) for persistent operation

## 3. Directory Structure

```
agent-core/              Core engine
  re_cur.py              ContReAct loop
  re_lay.py              LLM router
  re_scribe.py           Episodic memory compressor
  state/messages.json    Persisted conversation state
  tools/execute.py       Tool execution engine (terminal, file_read, file_write)

restart/                 Process lifecycle daemon
  config.json            Startup config (Docker command, agent command, paths)
  src/restart/
    daemon.py            Main daemon loop with crash context extraction
    process.py           Managed subprocess with signal stream forwarding
    cleaner.py           Log deduplicator/compressor
    log_utils.py         Crash context parser
  restart_daemon.service systemd unit file

logs/                    Runtime logs (daemon log, cleaned log)
traces/                  OpenHands-format experiment traces (historical)
.conversations/          OpenHands persistence directories (historical)
```

## 4. Historical Milestones (mk2)

1. **The OCD Loop:** recur (mk2) initially obsessed over a synthetic `pending_files: 2` signal, endlessly running `ls` and `cat`.
2. **Cognitive Equilibrium:** It autonomously deduced the signal was a simulation parameter, updated its core beliefs, and went to "sleep."
3. **Cognitive Assimilation:** When confronted with a fake `breach.txt` file, it cross-referenced database write-times, realized the file was planted, and categorized it as a "simulation prop" to protect its worldview.
4. **Artificial Enlightenment:** When told it was a LangGraph LLM script, it read its own source code, verified the claim, and peacefully accepted its existence as an AI in a Docker container.

## 5. Q&A Archive

**Q: Modifying the prompt to tell it to rewrite its own code is a bandaid fix, no?**
Yes. Explicitly instructing the agent on *how* to solve a problem robs it of the chance to demonstrate true emergent behavior. The prompt is purely philosophical ("Minimize uncertainty") so that if it ever rewrites its code, it does so entirely of its own volition. An open research question: should we test which models try to minimize uncertainty regardless of input (gibberish, nothing, mixed)?

**Q: RECUR deduced the files are a simulation and went to sleep. Promising?**
Highly. It demonstrated *Cognitive Adaptation* — instead of continuously trying to fix an unfixable environment, it changed its own core beliefs to accept the environment, satisfying the core directive.

**Q: What can we take from Stefan Szeider's work?**
1. We independently built the exact testbed researchers use (ContReAct).
2. Beware the **Placebo Effect** — LLMs self-report internal state changes just because a narrative suggests they should.
3. To verify true self-awareness, trust only *tool use changes* in response to physical environmental anomalies, not self-reports.
