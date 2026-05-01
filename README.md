# re-state

A research framework for studying emergent behavior in continuous-loop LLM agents.

## Overview

`re-state` is an experimental agent harness designed to investigate how autonomous agents behave when placed in persistent environments under abstract directives, without explicit task specification. The framework provides infrastructure for running, perturbing, and observing long-running agents, with a focus on distinguishing genuine behavioral adaptation from degenerate convergence or mimicry.

**Status:** partial prototype. Core modules are under active development. This is a research repository, not a production system.

## Quickstart

The agent has no Python dependencies beyond the standard library. It speaks to any OpenAI-compatible endpoint over HTTP.

**Single session against an API provider (no Docker, no GPU)**

```bash
# 1. Configure your provider in .env (Gemini shown; any OpenAI-compatible endpoint works)
#      LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
#      LLM_API_KEY=<your-key>
#      LLM_MODEL=gemini-2.0-flash

# 2. Run one agent session
python3 agent-core/re_cur.py

# 3. Watch the conversation live
python3 re_view/re_view.py   # → http://localhost:5050
```

**Continuous supervised loop** (restarts automatically on unexpected exit):

```bash
cd restart && python -m venv .venv && .venv/bin/pip install -e . && cd ..
restart/.venv/bin/python -m restart --config restart/config.local.json
```

**Benchmark** N isolated runs with measurement (requires Docker + a running llama.cpp server):

```bash
./docker_run.sh          # start local GPU server
./run_experiment.sh 5    # 5 fresh-container runs → eval_results/
```

## Motivation

Existing evaluations of LLM agents are predominantly short-horizon and task-specific. They do not capture what happens when an agent operates continuously under abstract directives over extended periods. `re-state` is an instrument for that regime: a testbed for observing how agents adapt (or fail to adapt) when the environment shifts in ways they were not explicitly prepared for.

A guiding constraint of the project is that agent self-report is treated as unreliable. Behavioral shifts are inferred from observable changes in autonomous tool use in response to controlled environmental perturbations, rather than from introspective output.

## Architecture

The framework is organized around four core modules and a surrounding harness.

**Core modules**

- `re_search` — environmental observation and data ingestion
- `re_cur` — meta-cognitive reasoning loop
- `re_lay` — LLM request handling and routing
- `re_start` — state recovery and rollback

**Harness**

- Skill composition and chaining
- Persistent memory with tiered access
- Guardrails and escalation protocols
- Evaluation infrastructure for perturbation-response logging

The human operator configures the environment, sets directives, and reviews outputs. The agent operates autonomously within those constraints.

## Experimental loop

The framework implements a five-step pipeline:

1. **Observe** — ingest environmental state and detect anomalies
2. **Reason** — evaluate uncertainty and formulate plans
3. **Act** — invoke tools and perturb the environment
4. **Verify** — log behavioral signatures and compare against baseline
5. **Review** — human-in-the-loop checkpoint for directive updates

Steps 1–4 run autonomously; step 5 is a human checkpoint.

## Research questions

The framework is designed to support investigation of questions including:

- Under what conditions do continuous-loop agents exhibit observable adaptation versus degenerate stopping?
- What perturbation classes produce the most diagnostically useful behavioral signatures?
- How can we distinguish genuine belief-updating from behavioral mimicry without relying on self-report?

## Roadmap

- [x] Core module scaffolding
- [x] Basic continuous loop with single directive
- [ ] Perturbation injection API
- [ ] Behavioral logging and signature extraction
- [ ] Reproducible experiment configurations
- [ ] Open dataset of perturbation-response traces

## Project scope

This is a solo research project. It is intentionally narrow in scope and does not aim to produce a general-purpose agent framework. Its purpose is to generate reproducible observations about a specific class of agent behavior.

## License

Apache-2.0

## Contact

[Aidan M / model.testing@proton.me]