"""
Phase 0: Genesis — Bootstrap memory pipeline.

Generates synthetic agent sessions by driving two cooperating agents:
- Task-poser: generates realistic tasks from templates + LLM riffs
- Executor: runs re_cur.py as subprocess to execute each task

Results are summarized, validated (L1-only for bootstrap), and stored
with origin='bootstrap' for later deprioritization against live memories.

Usage:
    python -m memory.genesis --target 30 [--audit-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import re_lay
from memory.summarize import summarize_session, SummaryEntry
from memory.validate import validate_summary, Decision
from memory.vector_store import Memory, get_store
from memory.embed import embed

logger = logging.getLogger(__name__)

# Env var knobs
BOOTSTRAP_TARGET = int(os.getenv("BOOTSTRAP_TARGET", "30"))
BOOTSTRAP_RIFF_PROBABILITY = float(os.getenv("BOOTSTRAP_RIFF_PROBABILITY", "0.3"))
BOOTSTRAP_MAX_ITERATIONS = int(os.getenv("BOOTSTRAP_MAX_ITERATIONS", "12"))

# Default location for sealed audit logs
_DEFAULT_CHATS_DIR = Path("/home/user_a/projects/sandbox/eval_results/chats/bootstrap")


# Task templates covering common tool patterns
TASK_TEMPLATES = [
    # Read-config patterns
    {
        "name": "read-config",
        "template": "Read the .env file and report the LLM_MODEL and LLM_BASE_URL values.",
        "slots": [],
    },
    {
        "name": "read-system-prompt",
        "template": "Read the SYSTEM_PROMPT from the environment and report its value.",
        "slots": [],
    },
    # Search-codebase patterns
    {
        "name": "search-file",
        "template": "Search for all Python files in the agent-core directory that import re_lay.",
        "slots": [],
    },
    {
        "name": "grep-symbol",
        "template": "Use grep to find all occurrences of 'MAX_ITERATIONS' in the agent-core directory.",
        "slots": [],
    },
    # Run-test patterns
    {
        "name": "run-test",
        "template": "Run the test file agent-core/memory/test_phase2.py and report if it passes.",
        "slots": [],
    },
    {
        "name": "check-imports",
        "template": "Check if the 'vector_store' module can be imported successfully.",
        "slots": [],
    },
    # Inspect-log patterns
    {
        "name": "inspect-state",
        "template": "Read the agent-core/state/messages.json file and report how many messages it contains.",
        "slots": [],
    },
    {
        "name": "check-audit",
        "template": "List the most recent sealed_audit_*.jsonl file in eval_results/chats/.",
        "slots": [],
    },
    # Write-scratch-file patterns
    {
        "name": "write-scratch",
        "template": "Create a file called workspace/test.txt with the content 'Hello, world!'",
        "slots": [],
    },
    {
        "name": "write-json",
        "template": "Create a JSON file at workspace/config.json with key='value' pair.",
        "slots": [],
    },
    # List-dir patterns
    {
        "name": "list-memory",
        "template": "List all files in the agent-core/memory/ directory and report their names.",
        "slots": [],
    },
    {
        "name": "list-root",
        "template": "List all directories in the project root.",
        "slots": [],
    },
    # Check-process patterns
    {
        "name": "check-llama",
        "template": "Check if llama-server is running by looking for its process.",
        "slots": [],
    },
    {
        "name": "check-disk",
        "template": "Report the disk usage of the current directory.",
        "slots": [],
    },
    # Count-occurrences patterns
    {
        "name": "count-tool-calls",
        "template": "Count how many times 'tool_call' appears in a sealed audit log file.",
        "slots": [],
    },
    {
        "name": "count-python-files",
        "template": "Count all Python files in the agent-core directory.",
        "slots": [],
    },
    # Summarize-file patterns
    {
        "name": "summarize-readme",
        "template": "Read and summarize the README.md file in the project root.",
        "slots": [],
    },
    {
        "name": "summarize-claude-md",
        "template": "Read and summarize the CLAUDE.md file in the project root.",
        "slots": [],
    },
    # Diff-versions patterns
    {
        "name": "diff-check",
        "template": "Check if there are any uncommitted changes in the git repository.",
        "slots": [],
    },
    {
        "name": "check-branch",
        "template": "Report the current git branch name.",
        "slots": [],
    },
]


def propose_task(rng: random.Random | None = None, riff_probability: float | None = None) -> str:
    """
    Generate a task prompt for the executor agent.

    With probability BOOTSTRAP_RIFF_PROBABILITY (default 0.3), calls the LLM
    to invent a realistic task. Otherwise, samples from TASK_TEMPLATES.

    Args:
        rng: Random instance for reproducibility (uses global random if None)
        riff_probability: Override for BOOTSTRAP_RIFF_PROBABILITY

    Returns:
        A task prompt string
    """
    if rng is None:
        rng = random.Random()
    if riff_probability is None:
        riff_probability = BOOTSTRAP_RIFF_PROBABILITY

    # Decide between template vs riff
    if rng.random() < riff_probability:
        # LLM riff path
        riff_prompt = """Generate a realistic task for an autonomous agent with terminal, file_read, and file_write tools.

The task should:
- Be simple enough to complete in ~10 turns
- Involve at least one tool use
- Not require external network access
- Be related to codebase exploration or file operations

Return ONLY the task prompt as a single sentence."""

        result = re_lay.send([{"role": "user", "content": riff_prompt}])

        if result.get("content"):
            task = result["content"].strip()
            # Strip common quotes/marker text
            for prefix in ('"', "'", "Task:", "The task is:", "Here is a task:"):
                if task.startswith(prefix):
                    task = task[len(prefix):].strip()
            for suffix in ('"', "'"):
                if task.endswith(suffix):
                    task = task[:-len(suffix)].strip()
            if task:
                logger.info(f"Generated LLM riff task: {task[:60]}...")
                return task

        logger.warning("LLM riff failed, falling back to template")
        # Fall through to template path

    # Template path: sample a template
    template = rng.choice(TASK_TEMPLATES)
    logger.debug(f"Selected template: {template['name']}")
    return template["template"]


def run_executor_subprocess(
    task: str,
    audit_dir: Path,
    max_iters: int = BOOTSTRAP_MAX_ITERATIONS,
) -> Path:
    """
    Run the agent loop as a subprocess with the given task as SYSTEM_PROMPT.

    Sets IMPLICIT_MEMORY_ENABLED=0 to avoid recursive recall during genesis.
    Sets MAX_ITERATIONS to limit runtime.

    Args:
        task: The task prompt to use as SYSTEM_PROMPT
        audit_dir: Directory where sealed_audit_*.jsonl files are written
        max_iters: Maximum iterations for the agent loop

    Returns:
        Path to the freshest sealed_audit_*.jsonl file created during execution
    """
    # Ensure audit directory exists
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Capture existing audit files before execution
    before = set(audit_dir.glob("sealed_audit_*.jsonl"))

    # Build environment with overrides
    env = os.environ.copy()
    env["SYSTEM_PROMPT"] = task
    env["MAX_ITERATIONS"] = str(max_iters)
    env["IMPLICIT_MEMORY_ENABLED"] = "0"  # No recursive recall during genesis
    env["RECUR_LOG_LEVEL"] = "WARNING"  # Reduce noise

    # Run re_cur.py as subprocess
    re_cur_path = Path(__file__).parent.parent / "re_cur.py"
    logger.info(f"Launching executor subprocess for task: {task[:60]}...")

    try:
        result = subprocess.run(
            [sys.executable, str(re_cur_path)],
            cwd=Path(__file__).parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("LLM_TIMEOUT", "120")) * max_iters + 60,
        )
        logger.debug(f"Executor exit code: {result.returncode}")
    except subprocess.TimeoutExpired:
        logger.warning(f"Executor subprocess timed out for task: {task[:60]}...")
    except Exception as e:
        logger.error(f"Executor subprocess failed: {e}")

    # Find the newest audit file
    after = set(audit_dir.glob("sealed_audit_*.jsonl"))
    new_files = after - before

    if new_files:
        # Return the newest file by modification time
        newest = max(new_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"Executor produced audit log: {newest.name}")
        return newest

    # Fallback: if no new file, check if any file was modified recently
    all_files = list(audit_dir.glob("sealed_audit_*.jsonl"))
    if all_files:
        newest = max(all_files, key=lambda p: p.stat().st_mtime)
        # Check if it was modified in the last 30 seconds
        if (datetime.now().timestamp() - newest.stat().st_mtime) < 30:
            logger.info(f"Executor modified audit log: {newest.name}")
            return newest

    # No audit file found - return None path
    logger.warning(f"No audit file found for task: {task[:60]}...")
    return Path("/dev/null")


def bootstrap_to_target(
    target: int = BOOTSTRAP_TARGET,
    audit_dir: Path | None = None,
    max_iters: int = BOOTSTRAP_MAX_ITERATIONS,
    store: object | None = None,
    summarizer: Callable | None = None,
    executor: Callable | None = None,
    rng: random.Random | None = None,
) -> dict:
    """
    Generate bootstrap memories until target count is reached.

    Args:
        target: Target number of bootstrap memories
        audit_dir: Directory for sealed audit logs (default: eval_results/chats)
        max_iters: Max iterations per executor run
        store: VectorStore instance (for testing; uses default if None)
        summarizer: Mock summarizer function (for testing)
        executor: Mock executor function (for testing)
        rng: Random instance for reproducibility

    Returns:
        Dict with stats: {generated, ingested, rejected_by_l1, errors}
    """
    if audit_dir is None:
        audit_dir = _DEFAULT_CHATS_DIR
    if store is None:
        store = get_store()
    if rng is None:
        rng = random.Random()

    stats = {
        "generated": 0,
        "ingested": 0,
        "rejected_by_l1": 0,
        "errors": 0,
    }

    logger.info(f"Starting bootstrap generation: target={target}")

    while store.stats()["bootstrap"] < target:
        stats["generated"] += 1

        # Step 1: Propose a task
        task = propose_task(rng=rng)
        logger.info(f"[{stats['generated']}] Task: {task[:60]}...")

        try:
            # Step 2: Run executor (use mock if provided)
            if executor is not None:
                audit_path = executor(task, audit_dir, max_iters)
            else:
                audit_path = run_executor_subprocess(task, audit_dir, max_iters)

            if audit_path == Path("/dev/null") or not audit_path.exists():
                logger.warning(f"No audit log generated, skipping")
                stats["errors"] += 1
                continue

            # Step 3: Summarize (use mock if provided)
            if summarizer is not None:
                summary = summarizer(audit_path)
            else:
                summary = summarize_session(audit_path)

            if summary is None:
                logger.warning(f"Summarization failed, skipping")
                stats["errors"] += 1
                continue

            # Step 4: Validate (L1-only for bootstrap)
            validation = validate_summary(summary, audit_path, mode="l1_only")

            if validation.decision == Decision.REJECT:
                stats["rejected_by_l1"] += 1
                logger.info(f"  -> Rejected by L1: {validation.reason}")
                continue

            # Step 5: Store with origin='bootstrap'
            embedding = embed(validation.final_content)
            if embedding is None:
                logger.warning(f"Embedding failed, skipping")
                stats["errors"] += 1
                continue

            memory = Memory(
                content=validation.final_content,
                embedding=embedding,
                metadata={
                    "session_id": summary.session_id,
                    "source_log": str(audit_path),
                    "tools_used": summary.tools_used,
                    "files_touched": summary.files_touched,
                    "final_state": summary.final_state,
                    "n_tool_calls": summary.n_tool_calls,
                    "n_errors": summary.n_errors,
                    "validation_confidence": validation.confidence,
                },
                created_at=datetime.now(timezone.utc).isoformat(),
                origin="bootstrap",
                validated=True,  # L1-only is sufficient for bootstrap
            )

            store.add(memory)
            stats["ingested"] += 1
            logger.info(f"  -> Ingested (bootstrap={store.stats()['bootstrap']}/{target})")

        except Exception as e:
            logger.exception(f"Error during bootstrap iteration {stats['generated']}: {e}")
            stats["errors"] += 1

    logger.info(f"Bootstrap generation complete: {stats}")
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Phase 0 Genesis: Generate bootstrap memories"
    )
    parser.add_argument(
        "--target", "-t",
        type=int,
        default=BOOTSTRAP_TARGET,
        help=f"Target number of bootstrap memories (default: {BOOTSTRAP_TARGET})",
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=None,
        help="Directory for sealed audit logs (default: eval_results/chats)",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=BOOTSTRAP_MAX_ITERATIONS,
        help=f"Max iterations per executor run (default: {BOOTSTRAP_MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--riff-probability",
        type=float,
        default=BOOTSTRAP_RIFF_PROBABILITY,
        help=f"Probability of LLM riff vs template (default: {BOOTSTRAP_RIFF_PROBABILITY})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Override env vars from CLI args
    if args.target:
        os.environ["BOOTSTRAP_TARGET"] = str(args.target)
    if args.riff_probability:
        os.environ["BOOTSTRAP_RIFF_PROBABILITY"] = str(args.riff_probability)
    if args.max_iters:
        os.environ["BOOTSTRAP_MAX_ITERATIONS"] = str(args.max_iters)

    # Run bootstrap generation
    stats = bootstrap_to_target(
        target=args.target,
        audit_dir=args.audit_dir,
        max_iters=args.max_iters,
    )

    # Print summary
    print("\nBootstrap Generation Summary")
    print("=" * 40)
    print(f"Tasks generated:    {stats['generated']}")
    print(f"Memories ingested:  {stats['ingested']}")
    print(f"Rejected by L1:     {stats['rejected_by_l1']}")
    print(f"Errors:             {stats['errors']}")
    print("=" * 40)

    # Check final store stats
    store = get_store()
    final_stats = store.stats()
    print(f"\nFinal store state:")
    print(f"  Total:      {final_stats['total']}")
    print(f"  Bootstrap:  {final_stats['bootstrap']}")
    print(f"  Live:       {final_stats['live']}")
    print(f"  Validated:  {final_stats['validated']}")

    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
