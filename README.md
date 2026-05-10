# re-state

A research framework for studying emergent behavior in continuous-loop LLM agents. Implements ContReAct (Continuous Reasoning + Acting) — a persistent, task-free loop that allows agents to explore, create tools, and modify their approach autonomously under abstract directives.

**Status:** Unvalidated research scaffolding. Treat all behavior described here as *intended* behavior, not confirmed.

## Quickstart

```bash
# Configure .env with your provider
LLM_BASE_URL=<provider URL>
LLM_API_KEY=<your key>
LLM_MODEL=<model name>

# Run one agent session
python3 agent-core/re_cur.py

# Run benchmark (5 isolated runs)
./run_experiment.sh 5
```

## Architecture

**Core Loop** (`agent-core/`):
- `re_cur.py` — ContReAct loop with message eviction and circuit breakers
- `re_lay.py` — OpenAI-format client with terminal/file_read/file_write tools
- `tools/execute.py` — Tool dispatch with protected path enforcement
- `sealed_audit.py` — Tamper-proof audit log

**Memory Pipeline** (`agent-core/memory/`):
- `vector_store.py` — SQLite + cosine similarity search
- `embed.py` — Text → 384d vectors (all-MiniLM-L6-v2)
- `recall.py` — Keyword-gated retrieval with similarity threshold
- `sleep_cycle.py` — Summarization + validation pipeline
- `genesis.py` — Bootstrap memory generation for cold-start
- `prune.py` — Bootstrap memory lifecycle management

## Roadmap Status

| Phase | Component | Status |
|-------|-----------|--------|
| 0 | Bootstrap memory generation | ✅ Complete |
| 1 | Structured JSONL logging | ✅ Complete |
| 2 | Vector store + embedding | ✅ Complete |
| 3 | Runtime memory retrieval | ✅ Complete |
| 4 | Sleep cycle summarization | ✅ Complete |
| 5 | Three-layer validation | ✅ Complete |
| 6 | Embedding model fine-tuning | 🚧 Pending |
| 7 | Memory lifecycle (decay/consolidate) | ✅ Partial (pruning only) |

## Hardware Budget

Target: 8GB VRAM

| Component | VRAM |
|-----------|------|
| Reasoning LLM (7B Q4) | ~4.5GB |
| Embedding model | ~0.2GB |
| Overhead | ~0.8GB |
| **Total** | **~5.5GB** |

## License

Apache-2.0
