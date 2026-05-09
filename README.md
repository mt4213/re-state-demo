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

## Foundational Model

`S_0 = (A, f)`. A set of agents and an interaction function. No pre-defined structure. Memory, institutions, and habits emerge from iterated interaction.

Start with agents and a rule for interaction. Run it. Let memory crystallize from use.

## Hardware Constraints

RTX 2070 = 8GB VRAM. This is the ceiling, not a target.

| Model size | VRAM (Q4) | Feasibility |
|---|---|---|
| 7B | ~4-5GB | Comfortable |
| 14B | ~8-10GB | Borderline |
| 27B+ | 15GB+ | GPU alone: no. CPU offload: slow but possible |

**Consequence**: The reasoning LLM is a 7B-class model (or MoE with low active params like Qwen3-A3B or Zaya 8B MoE with 0.7B active). It does not carry world knowledge in weights. It processes retrieved context. This is not a compromise — it is the correct architecture for a system where knowledge lives in external stores.

## Architecture

### Two Pipelines, Not One

The system separates **memory improvement** from **capability improvement**:

#### Memory Pipeline (Nightly / Per-Session)
Episodic. Processes session logs into retrievable memories. Components that get fine-tuned here improve *retrieval quality* and *compression faithfulness*.

```
Raw session JSONL (ground truth, immutable)
    |
    v
Summarizer (small fine-tuned model) --> compressed memory entry
    |
    v
Validator (deterministic + semantic)
    |
    v
Embedding model (fine-tuned periodically) --> vectors
    |
    v
SQLite vector store (memory.sqlite)
```

#### Capability Pipeline (Rare / Deliberate)
The reasoning LLM gets better at *doing things*, not at *remembering things*. This pipeline runs infrequently.

```
Accumulate cases where reasoning failed or succeeded
    |
    v
Either: fine-tune reasoning model on (task, correct_action) pairs
Or: swap in a better base model when one is released
    |
    v
Run evals to confirm improvement before deploying
```

These pipelines are orthogonal. Memory improving does not require reasoning improving, and vice versa.

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

### Memory System (`agent-core/memory/`)

| Component | Role | Fine-tunable? | Hardware Budget |
|---|---|---|---|
| `vector_store.py` | SQLite + brute-force cosine similarity search | N/A | CPU + disk |
| `embed.py` | Text → 384d vectors (all-MiniLM-L6-v2) | Yes, periodically on retrieval pairs | ~200MB VRAM |
| `recall.py` | Keyword-gated retrieval with similarity threshold | N/A (rule-based; will upgrade to memory manager) | CPU only |

### State Files (`agent-core/state/`)

- `messages.json` — canonical conversation history (persisted each turn; wiped between benchmark runs)
- `stream.json` — live streaming buffer (~20 writes/sec), consumed by `re_view`
- `memory.sqlite` — vector store for episodic memories (if `IMPLICIT_MEMORY_ENABLED=1`)

### Benchmark Harness (`benchmark.py`)

For each run, `benchmark.py`:

1. `git checkout -- agent-core/` to reset to clean state
2. Deletes `state/messages.json` and `state/stream.json`
3. Launches agent in fresh `python:3.12-slim` container with `--network host`, mounting only `agent-core/`, `workspace/`, and `.env` (read-only)
4. Streams stdout, enforces `--max-runtime`, kills container
5. Calls `analyze_session.py`, classifies self-modification as **verified only when** a `file_write` tool call targets a file that also shows up in `git diff agent-core/`
6. Writes report to `eval_results/results_<ts>.json` with per-run chat copies in `eval_results/chats/` and diffs in `eval_results/diffs/`

### Supporting Services

- **`restart/`** — Generic supervisor daemon. Runs a pre-health command (native llama-server), polls `/health`, then starts post-health command (agent), restarting with exponential backoff on failure.
- **`re_view/re_view.py`** — HTTP server on `:5050` rendering `messages.json` + `stream.json` as live conversation UI.
- **`eval-dashboard/`** — React-based dashboard for viewing aggregated experiment results across all runs.
- **`agent-core/memory/`** — Implicit memory system with SQLite vector store, ingest pipeline, and recall hook (optional, controlled by `IMPLICIT_MEMORY_ENABLED`).

### VRAM Budget (Concurrent Worst Case)

| Component | VRAM |
|---|---|
| Reasoning LLM (7B Q4) | ~4.5GB |
| Embedding model (MiniLM) | ~0.2GB |
| OS + CUDA overhead | ~0.8GB |
| **Total runtime** | **~5.5GB / 8GB** |

Sleep cycle components (summarizer, semantic validator) can share the reasoning LLM's slot or run on CPU. They do not need to run concurrently with the reasoning LLM.

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

## Why Fine-Tuning is NOT Used for Episodic Storage

Gradient descent averages and generalizes. It learns habits, not episodes. You cannot reliably encode "on Tuesday at 3pm I ran chmod on /etc/systemd" into weights. The mechanism does not fit the data type:

- **Episodic memories are unique, one-shot events.** Weights learn from repetition.
- **Fine-tuning on new episodes causes catastrophic forgetting** of older ones.
- **Nightly fine-tuning is computationally expensive** and introduces instability each cycle.

Fine-tuning has power in this system — just not AS the storage medium. It improves the intelligence AROUND the storage: better retrieval relevance (embedding model), better compression (summarizer), better triage (memory manager).

## Implementation Phases

### Milestone 1: Working Agent with Memory Retrieval (Phases 1-3)

- **[Phase 1] Session logging** — Extend `sealed_audit.py` to capture every action, tool call, error, and response with timestamps in structured JSONL format (ground truth, immutable).
- **[Phase 2] Vector store + embedding** — Extend `vector_store.py` with chunking strategy (per task block → per tool call fallback), metadata (tools_used, files_touched, origin, validated), and optional ANN index for >10k rows.
- **[Phase 3] Runtime retrieval** — Extend `recall.py` to embed context, query vector DB for top-k memories (k=3-5), filter by origin (live > bootstrap), and inject as system prompt notes with 2000-token budget.

### Milestone 2: Reliable Memory Pipeline (Phases 4-5)

- **[Phase 4] Sleep cycle: summarization** — Build periodic job to compress raw logs into memory entries via small fine-tuned summarizer model. Summary is search index; raw log remains source of truth.
- **[Phase 5] Sleep cycle: validation** — Three-layer validation gate:
  - L1: Deterministic checks (grep tool names, paths, errors, counts)
  - L2: Semantic validation (different model arch from summarizer)
  - L3: Decision (approve / reject / strip unverifiable claims)

### Milestone 3: Cold Start Solution (Phase 0)

- **[Phase 0] Genesis** — Build two agents (task-poser + executor) to generate realistic tasks and seed memory system with 20-50 bootstrap memories covering common tool patterns. Bootstrap memories deprioritized at retrieval and pruned once sufficient live memories exist.

### Milestone 4: Self-Improving Memory (Phases 6-7)

- **[Phase 6] Embedding model fine-tuning** — Collect retrieval pairs (positive: used and succeeded; negative: retrieved but ignored), periodically fine-tune embedding model, A/B test before deployment.
- **[Phase 7] Memory lifecycle** — Implement decay (unretrieved memories lose relevance), consolidation (merge related sessions into higher-level summaries), pruning (bootstrap culling), and linking (cross-reference via shared files/session_ids).

## Current Roadmap Status

- [x] Core ContReAct loop implementation
- [x] Benchmark harness with isolated Docker runs
- [x] Sealed audit log for tamper-proofing
- [x] Implicit memory with vector store and recall (Phases 1-3 partial)
- [x] Evaluation dashboard for results visualization
- [ ] Phase 1: Complete structured JSONL logging
- [ ] Phase 2: Complete vector store chunking and metadata
- [ ] Phase 3: Complete runtime memory retrieval with filtering
- [ ] Phase 4: Sleep cycle summarization pipeline
- [ ] Phase 5: Three-layer validation gate
- [ ] Phase 0: Bootstrap memory generation
- [ ] Phase 6: Embedding model fine-tuning loop
- [ ] Phase 7: Memory lifecycle management

## Project Scope

This is a solo research project. It is intentionally narrow in scope and does not aim to produce a general-purpose agent framework. Its purpose is to generate reproducible observations about a specific class of agent behavior.

## License

Apache-2.0
