"""
Phase 4: Sleep-cycle batch processing.

Scans eval_results/chats/ for new session logs (those without a summary),
runs the summarizer on each, and writes SummaryEntry files alongside.

Idempotent: re-running skips already-summarized sessions.

Usage:
    python -m memory.sleep_cycle [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.summarize import summarize_session, SummaryEntry

logger = logging.getLogger(__name__)

# Default location for sealed audit logs
_DEFAULT_CHATS_DIR = Path("/home/user_a/projects/sandbox/eval_results/chats")


def _get_chats_dir() -> Path:
    """Get the directory containing sealed audit logs."""
    # Check env var first (for benchmark runs)
    env_path = os.getenv("SEALED_AUDIT_DIR")
    if env_path:
        return Path(env_path)

    # Use default
    return _DEFAULT_CHATS_DIR


def _find_unsummarized_sessions(chats_dir: Path) -> list[Path]:
    """
    Find all sealed_audit_*.jsonl files without a corresponding .summary.json.
    """
    if not chats_dir.exists():
        logger.warning(f"Chats directory does not exist: {chats_dir}")
        return []

    unsummarized = []
    for jsonl_path in sorted(chats_dir.glob("sealed_audit_*.jsonl")):
        summary_path = jsonl_path.with_suffix(".summary.json")
        if not summary_path.exists():
            unsummarized.append(jsonl_path)

    return unsummarized


def _write_summary(summary: SummaryEntry, jsonl_path: Path) -> Path:
    """Write SummaryEntry to a .summary.json file alongside the JSONL."""
    summary_path = jsonl_path.with_suffix(".summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)
    return summary_path


def run_sleep_cycle(
    chats_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Run the sleep cycle: summarize all unsummarized sessions.

    Args:
        chats_dir: Directory containing sealed_audit_*.jsonl files
        dry_run: If True, scan and report but don't write summaries

    Returns:
        Dict with stats: total_scanned, already_summarized, newly_summarized, failed
    """
    chats_dir = chats_dir or _get_chats_dir()

    stats = {
        "total_scanned": 0,
        "already_summarized": 0,
        "newly_summarized": 0,
        "failed": 0,
        "summary_paths": [],
    }

    # Find all JSONL files
    if not chats_dir.exists():
        logger.error(f"Chats directory does not exist: {chats_dir}")
        return stats

    all_jsonl = list(chats_dir.glob("sealed_audit_*.jsonl"))
    stats["total_scanned"] = len(all_jsonl)

    for jsonl_path in all_jsonl:
        summary_path = jsonl_path.with_suffix(".summary.json")

        if summary_path.exists():
            stats["already_summarized"] += 1
            logger.debug(f"Skipping (already summarized): {jsonl_path.name}")
            continue

        logger.info(f"Summarizing: {jsonl_path.name}")

        if dry_run:
            stats["newly_summarized"] += 1
            stats["summary_paths"].append(str(summary_path) + " (dry-run)")
            continue

        try:
            summary = summarize_session(jsonl_path)
            if summary is None:
                stats["failed"] += 1
                logger.warning(f"Failed to summarize: {jsonl_path.name}")
                continue

            written_path = _write_summary(summary, jsonl_path)
            stats["newly_summarized"] += 1
            stats["summary_paths"].append(str(written_path))
            logger.info(f"  -> Wrote: {written_path.name}")

        except Exception as e:
            stats["failed"] += 1
            logger.exception(f"Error summarizing {jsonl_path.name}: {e}")

    return stats


def print_stats(stats: dict):
    """Pretty-print sleep cycle stats."""
    print(f"\nSleep Cycle Report ({datetime.now().isoformat()})")
    print("=" * 50)
    print(f"Total scanned:     {stats['total_scanned']}")
    print(f"Already summarized:{stats['already_summarized']}")
    print(f"Newly summarized:  {stats['newly_summarized']}")
    print(f"Failed:            {stats['failed']}")
    print("=" * 50)

    if stats["summary_paths"]:
        print("\nSummary files written:")
        for path in stats["summary_paths"][:10]:
            print(f"  - {path}")
        if len(stats["summary_paths"]) > 10:
            print(f"  ... and {len(stats['summary_paths']) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Sleep cycle: summarize unsummarized session logs"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report but don't write summaries",
    )
    parser.add_argument(
        "--chats-dir",
        type=Path,
        default=None,
        help="Directory containing sealed_audit_*.jsonl files",
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

    stats = run_sleep_cycle(
        chats_dir=args.chats_dir,
        dry_run=args.dry_run,
    )
    print_stats(stats)

    # Exit with error code if any failures
    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
