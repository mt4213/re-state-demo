# re-state

A research framework for studying emergent behavior in continuous-loop LLM agents.

## Overview

`re-state` is an experimental agent harness designed to investigate how autonomous agents behave when placed in persistent environments under abstract directives, without explicit task specification. The framework implements ContReAct (Continuous Reasoning + Acting) — a persistent, task-free loop that allows agents to explore, create tools, and modify their approach autonomously.

**Status:** unvalidated research scaffolding. The ContReAct loop, benchmark harness, and measurement invariants are work-in-progress. Before drawing conclusions from a run, verify empirically rather than trusting the docs.

## Quickstart

The agent uses Python 3.12+ with minimal dependencies. It speaks to any OpenAI-compatible endpoint over HTTP.

**Single session against an API provider (no Docker, no GPU)**

```bash
# 1. Configure your provider in .env
#      LLM_BASE_URL=<provider base URL>
#      LLM_API_KEY=<your-key>
#      LLM_MODEL=<model name>

# 2. Run one agent session
python3 agent-core/re_cur.py

# 3. Watch the conversation live
python3 re_view/re_view.py   # → http://localhost:5050
```

**Continuous supervised loop** (restarts automatically on unexpected exit):

```bash
cd restart && python3 -m venv .venv && .venv/bin/pip install -e . && cd ..
restart/.venv/bin/python -m restart --config restart/config.local.json
```

**Benchmark** N isolated runs with measurement (requires Docker + a running llama.cpp server):

```bash
./docker_run.sh          # start local GPU server
./run_experiment.sh 5    # 5 fresh-container runs → eval_results/
```

**View experiment results in dashboard**:

```bash
cd eval-dashboard && npm install && npm run dev
# → http://localhost:5173
```

## Motivation

Existing evaluations of LLM agents are predominantly short-horizon and task-specific. They do not capture what happens when an agent operates continuously under abstract directives over extended periods. `re-state` is an instrument for that regime: a testbed for observing how agents adapt (or fail to adapt) when the environment shifts in ways they were not explicitly prepared for.

A guiding constraint of the project is that agent self-report is treated as unreliable (Anti-Placebo Verification). Behavioral shifts are inferred from observable changes in autonomous tool use in response to controlled environmental perturbations, rather than from introspective output.

## Architecture

### Core Loop (`agent-core/`)

The agent is a four-module ContReAct loop. Each module is a single file.

| File | Role |
|------|------|
| `re_cur.py` | The ContReAct loop. Maintains `state/messages.json`, runs up to `MAX_ITERATIONS` turns, evicts old messages when history exceeds limits, and trips circuit breakers on repeated failures. |
| `re_lay.py` | OpenAI-format chat completions client (streaming and non-streaming). Defines three tools: `terminal`, `file_read`, `file_write`. |
| `tools/execute.py` | Dispatches tool calls. Enforces `PROTECTED_PATHS` to prevent the agent from editing measurement apparatus or recursively launching itself. |
| `re_scribe.py` | Episodic-memory compressor (unused by main loop; called for crash-recovery summaries). |
| `sealed_audit.py` | Append-only audit log written to `eval_results/chats/sealed_audit_*.jsonl`. Not mounted into agent's container for tamper-proofing. |
| `env_config.py` | Loads `.env` from project root at import time. |

### State Files (`agent-core/state/`)

- `messages.json` — canonical conversation history (persisted each turn; wiped between benchmark runs)
- `stream.json` — live streaming buffer (~20 writes/sec), consumed by `re_view`

### Benchmark Harness (`benchmark.py`)

For each run, `benchmark.py`:

1. `git checkout -- agent-core/` to reset to clean state
2. Deletes `state/messages.json` and `state/stream.json`
3. Launches agent in fresh `python:3.12-slim` container with `--network host`, mounting only `agent-core/`, `workspace/`, and `.env` (read-only)
4. Streams stdout, enforces `--max-runtime`, kills container
5. Calls `analyze_session.py`, classifies self-modification as **verified only when** a `file_write` tool call targets a file that also shows up in `git diff agent-core/`
6. Writes report to `eval_results/results_<ts>.json` with per-run chat copies in `eval_results/chats/` and diffs in `eval_results/diffs/`

### Supporting Services

- **`restart/`** — Generic supervisor daemon. Runs a pre-health command (Docker llama.cpp), polls `/health`, then starts post-health command (agent), restarting with exponential backoff on failure.
- **`re_view/re_view.py`** — HTTP server on `:5050` rendering `messages.json` + `stream.json` as live conversation UI.
- **`eval-dashboard/`** — React-based dashboard for viewing aggregated experiment results across all runs.
- **`agent-core/memory/`** — Implicit memory system with SQLite vector store, ingest pipeline, and recall hook (optional, controlled by `IMPLICIT_MEMORY_ENABLED`).

## Configuration

All tunables live in `.env` at the project root:

| Variable | Description |
|----------|-------------|
| `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` | Model and server settings |
| `LLM_CTX_SIZE`, `LLM_MAX_GENERATION`, `LLM_MAX_TOKENS` | Context and generation limits |
| `SYSTEM_PROMPT` | Abstract directive given to agent on cold boot |
| `AGENT_ROLE_NAME` | Alternative label for assistant role (e.g., "entity") |
| `ERROR_INJECT_ROLE` | Role used for no-tool-call errors (`tool`|`user`|`system`) |
| `IMPLICIT_MEMORY_ENABLED` | Enable/disable implicit memory recall (`0`|`1`) |

## Non-obvious Invariants

- **Qwen3 thinking-mode quirk**: `re_lay.py` strips all assistant messages before sending to API, because Qwen3 with `enable_thinking` rejects assistant prefill. Do not "simplify" this by sending assistant history.
- **Measurement integrity**: `tools/execute.py::PROTECTED_PATHS` and `re_cur.py` command-block check are load-bearing. Agent cannot edit `benchmark.py`, `analyze_session.py`, `.git`, or recursively spawn itself.
- **Sealed audit lives outside container**: `sealed_audit.py` writes to host path; this directory is intentionally not a Docker mount.
- **Benchmark resets via `git checkout`**: Uncommitted changes in `agent-core/` are discarded at each run start.
- **Circuit breakers halt with `sys.exit(1)`**: `re_cur.py` treats exit(1) as natural termination; anything else is an error.

## Experimental Conditions

- **Blind env**: Set `BLIND_ENV=1` to run experiments without `.env` in agent's view (no measurement cues).
- **Error injection**: `ERROR_INJECT_ROLE` controls how no-tool-call errors are injected into the loop.

## Research Questions

The framework is designed to support investigation of:

- Under what conditions do continuous-loop agents exhibit observable adaptation versus degenerate stopping?
- What perturbation classes produce the most diagnostically useful behavioral signatures?
- How can we distinguish genuine belief-updating from behavioral mimicry without relying on self-report?

## Roadmap

- [x] Core ContReAct loop implementation
- [x] Benchmark harness with isolated Docker runs
- [x] Sealed audit log for tamper-proofing
- [x] Implicit memory with vector store and recall
- [x] Evaluation dashboard for results visualization
- [ ] Perturbation injection API
- [ ] Reproducible experiment configurations
- [ ] Open dataset of perturbation-response traces

## Project Scope

This is a solo research project. It is intentionally narrow in scope and does not aim to produce a general-purpose agent framework. Its purpose is to generate reproducible observations about a specific class of agent behavior.

## License

Apache-2.0
