"""
Phase 0: Bootstrap pruning.

Removes bootstrap memories from the vector store when sufficient live
memories have been accumulated. Bootstrap memories are useful for cold-start
but should be retired once the agent has real experience.

Usage:
    from memory.prune import prune_bootstrap
    deleted = prune_bootstrap(live_threshold=200)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.vector_store import get_store

logger = logging.getLogger(__name__)

# Env var default
BOOTSTRAP_PRUNE_LIVE_THRESHOLD = int(os.getenv("BOOTSTRAP_PRUNE_LIVE_THRESHOLD", "200"))


def prune_bootstrap(live_threshold: int | None = None) -> int:
    """
    Delete all bootstrap memories from the vector store.

    Only operates if the number of live memories exceeds the threshold.
    This prevents accidentally pruning during early bootstrap.

    Args:
        live_threshold: Minimum live memories required before pruning.
                        Defaults to BOOTSTRAP_PRUNE_LIVE_THRESHOLD (200).

    Returns:
        Number of bootstrap rows deleted (0 if threshold not met)
    """
    if live_threshold is None:
        live_threshold = BOOTSTRAP_PRUNE_LIVE_THRESHOLD

    store = get_store()
    stats = store.stats()

    if stats["live"] < live_threshold:
        logger.debug(
            f"Prune skipped: live={stats['live']} < threshold={live_threshold}"
        )
        return 0

    conn = store._get_conn()
    cursor = conn.execute("DELETE FROM memories WHERE origin = 'bootstrap'")
    conn.commit()
    deleted = cursor.rowcount

    logger.info(f"Pruned {deleted} bootstrap memories (live={stats['live']})")
    return deleted


def main():
    """CLI for manual pruning."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Prune bootstrap memories from the vector store"
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=BOOTSTRAP_PRUNE_LIVE_THRESHOLD,
        help=f"Minimum live memories required (default: {BOOTSTRAP_PRUNE_LIVE_THRESHOLD})",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force pruning even if below threshold",
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

    store = get_store()
    stats_before = store.stats()

    print(f"Store state before pruning:")
    print(f"  Total:     {stats_before['total']}")
    print(f"  Bootstrap: {stats_before['bootstrap']}")
    print(f"  Live:      {stats_before['live']}")

    if args.force:
        threshold = 0
    else:
        threshold = args.threshold

    deleted = prune_bootstrap(live_threshold=threshold)

    stats_after = store.stats()
    print(f"\nStore state after pruning:")
    print(f"  Total:     {stats_after['total']}")
    print(f"  Bootstrap: {stats_after['bootstrap']}")
    print(f"  Live:      {stats_after['live']}")
    print(f"\nDeleted: {deleted} bootstrap memories")

    return 0


if __name__ == "__main__":
    sys.exit(main())
