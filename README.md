# re-state

## Quickstart

```bash
# Configure .env with your provider
LLM_BASE_URL=<provider URL>
LLM_API_KEY=<your key>
LLM_MODEL=<model name>

# Run one agent session
python3 agent-core/re_cur.py

# Run benchmark (N isolated runs)
./run_experiment.sh N
```

## Architecture

**Loop** (`agent-core/`):
- `re_cur.py` Cont(inuous)-Re(ason)-Act(tools) loop with message eviction and circuit breakers
- `re_lay.py` OpenAI-format client with terminal/file_read/file_write tools
- `tools/execute.py` Tool dispatch with protected path enforcement
- `sealed_audit.py` Tamper-proof audit log

**Memory Pipeline** (`agent-core/memory/`):
- `vector_store.py` SQLite + cosine similarity search
- `embed.py` Text → 384d vectors
- `recall.py` Keyword-gated retrieval with similarity threshold
- `sleep_cycle.py` Summarization + validation pipeline
- `genesis.py`  memory generation for cold-start
- `prune.py` memory lifecycle management

## License

Apache-2.0
