"""
Phase 5: Sleep-cycle batch processing with validation.

Scans eval_results/chats/ for new session logs, summarizes, validates (L1/L2/L3),
and writes approved summaries to the vector DB with validated=True.

Reject flow: re-summarize once with stricter prompt; if still rejected,
fall back to storing raw log chunks as Memory entries with validated=False.

Idempotent: re-running skips already-validated sessions.

Usage:
    python -m memory.sleep_cycle [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.summarize import summarize_session, SummaryEntry, _load_jsonl
from memory.validate import (
    validate_summary,
    ValidationResult,
    Decision,
    re_summarize_strict,
)
from memory.vector_store import Memory, get_store
from memory.embed import embed
from memory.prune import prune_bootstrap

logger = logging.getLogger(__name__)

# Default location for sealed audit logs
_DEFAULT_CHATS_DIR = Path("/home/user_a/projects/sandbox/eval_results/chats")


def _get_chats_dir() -> Path:
    """Get the directory containing sealed audit logs."""
    env_path = os.getenv("SEALED_AUDIT_DIR")
    if env_path:
        return Path(env_path)
    return _DEFAULT_CHATS_DIR


def _find_pending_sessions(chats_dir: Path) -> list[Path]:
    """
    Find all sealed_audit_*.jsonl files without a .validated.json marker.
    """
    if not chats_dir.exists():
        logger.warning(f"Chats directory does not exist: {chats_dir}")
        return []

    pending = []
    for jsonl_path in sorted(chats_dir.glob("sealed_audit_*.jsonl")):
        validated_path = jsonl_path.with_suffix(".validated.json")
        if not validated_path.exists():
            pending.append(jsonl_path)

    return pending


def _write_summary(summary: SummaryEntry, jsonl_path: Path) -> Path:
    """Write SummaryEntry to a .summary.json file alongside the JSONL."""
    summary_path = jsonl_path.with_suffix(".summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)
    return summary_path


def _write_validation_marker(
    jsonl_path: Path,
    validation_result: ValidationResult,
    final_content: str,
) -> Path:
    """Write .validated.json marker to indicate session was processed."""
    validated_path = jsonl_path.with_suffix(".validated.json")
    marker = {
        "session_id": validation_result.metadata.get("session_id"),
        "decision": validation_result.decision,
        "confidence": validation_result.confidence,
        "reason": validation_result.reason,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "final_content_length": len(final_content),
    }
    with open(validated_path, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2, ensure_ascii=False)
    return validated_path


def _extract_raw_chunks(jsonl_path: Path, n_chunks: int = 2) -> list[str]:
    """
    Fall back to storing raw log chunks when validation fails.
    Returns the n_chunks longest tool_call output blocks.
    """
    events = _load_jsonl(jsonl_path)

    # Find tool_call events with longest output
    tool_outputs = []
    for event in events:
        if event.get("type") == "tool_call":
            output = event.get("output", "")
            if output:
                tool_outputs.append((output, len(output)))

    # Sort by length descending and take top n
    tool_outputs.sort(key=lambda x: x[1], reverse=True)
    return [output for output, _ in tool_outputs[:n_chunks]]


def _store_in_vector_db(
    content: str,
    summary: SummaryEntry,
    validation_result: ValidationResult,
    origin: str = "live",
) -> bool:
    """
    Embed and store validated summary in vector DB.

    Returns True if successful, False otherwise.
    """
    try:
        # Generate embedding
        embedding = embed(content)
        if embedding is None:
            logger.warning("Embedding failed, skipping vector DB write")
            return False

        # Build metadata
        metadata = {
            "session_id": summary.session_id,
            "source_log": summary.source_log_path,
            "tools_used": summary.tools_used,
            "files_touched": summary.files_touched,
            "final_state": summary.final_state,
            "n_tool_calls": summary.n_tool_calls,
            "n_errors": summary.n_errors,
            "validation_confidence": validation_result.confidence,
            "validation_decision": validation_result.decision,
        }

        # Create Memory entry
        memory = Memory(
            content=content,
            embedding=embedding,
            metadata=metadata,
            created_at=datetime.now(timezone.utc).isoformat(),
            origin=origin,
            validated=True,  # Only store validated summaries
        )

        # Add to vector store
        store = get_store()
        store.add(memory)
        logger.info(f"  -> Stored in vector DB (confidence={validation_result.confidence})")
        return True

    except Exception as e:
        logger.error(f"Failed to store in vector DB: {e}")
        return False


def _process_session(
    jsonl_path: Path,
    dry_run: bool = False,
) -> dict:
    """
    Process a single session through summarize -> validate -> store pipeline.

    Returns:
        Dict with status, decision, and any error info.
    """
    result = {
        "jsonl_path": str(jsonl_path),
        "status": "unknown",
        "decision": None,
        "stored_in_db": False,
        "error": None,
    }

    try:
        # Step 1: Summarize
        logger.info(f"Processing: {jsonl_path.name}")
        summary = summarize_session(jsonl_path)
        if summary is None:
            result["status"] = "failed"
            result["error"] = "summarization failed"
            return result

        # Write summary file (for debugging/inspection)
        if not dry_run:
            _write_summary(summary, jsonl_path)

        # Step 2: Validate
        validation = validate_summary(summary, jsonl_path)
        result["decision"] = validation.decision

        # Step 3: Handle decision
        final_content = validation.final_content
        origin = "live"
        validated = True

        if validation.decision == Decision.APPROVE:
            result["status"] = "approved"
            logger.info(f"  -> Approved (confidence={validation.confidence})")

        elif validation.decision == Decision.APPROVE_STRIPPED:
            result["status"] = "approved_stripped"
            logger.info(f"  -> Approved with stripped content (confidence={validation.confidence})")

        elif validation.decision == Decision.REJECT:
            # Re-summarize with stricter prompt
            logger.info(f"  -> Rejected, re-summarizing with stricter prompt...")
            stricter_content = re_summarize_strict(jsonl_path)

            if stricter_content:
                # Re-validate the stricter summary
                stricter_summary = SummaryEntry(
                    content=stricter_content,
                    metadata=summary.metadata,
                    session_id=summary.session_id,
                    started_at=summary.started_at,
                    ended_at=summary.ended_at,
                    tools_used=summary.tools_used,
                    files_touched=summary.files_touched,
                    n_tool_calls=summary.n_tool_calls,
                    n_errors=summary.n_errors,
                    final_state=summary.final_state,
                    source_log_path=summary.source_log_path,
                )
                re_validation = validate_summary(stricter_summary, jsonl_path)

                if re_validation.decision in (Decision.APPROVE, Decision.APPROVE_STRIPPED):
                    final_content = re_validation.final_content
                    result["status"] = "approved_after_re_summarize"
                    result["decision"] = re_validation.decision
                    logger.info(f"  -> Re-summarize passed (decision={re_validation.decision})")
                else:
                    # Still rejected - fall back to raw chunks
                    logger.info(f"  -> Re-summarize still rejected, falling back to raw chunks...")
                    chunks = _extract_raw_chunks(jsonl_path, n_chunks=2)
                    if chunks:
                        final_content = " | ".join(chunks[:2])
                        origin = "live"
                        validated = False  # Raw chunks not validated via LLM
                        result["status"] = "fallback_raw_chunks"
                        logger.info(f"  -> Stored {len(chunks)} raw chunks as fallback")
                    else:
                        result["status"] = "failed"
                        result["error"] = "validation rejected and no raw chunks available"
                        return result
            else:
                # Strict re-summarization failed - fall back to raw chunks
                logger.info(f"  -> Strict re-summarization failed, falling back to raw chunks...")
                chunks = _extract_raw_chunks(jsonl_path, n_chunks=2)
                if chunks:
                    final_content = " | ".join(chunks[:2])
                    origin = "live"
                    validated = False
                    result["status"] = "fallback_raw_chunks"
                    logger.info(f"  -> Stored {len(chunks)} raw chunks as fallback")
                else:
                    result["status"] = "failed"
                    result["error"] = "re-summarization failed and no raw chunks available"
                    return result

        # Step 4: Store in vector DB (unless dry run)
        if not dry_run:
            if validated:
                stored = _store_in_vector_db(final_content, summary, validation, origin)
                result["stored_in_db"] = stored
            else:
                # Raw chunks - still store but with validated=False
                try:
                    embedding = embed(final_content)
                    if embedding:
                        memory = Memory(
                            content=final_content,
                            embedding=embedding,
                            metadata={"session_id": summary.session_id, "fallback": True},
                            created_at=datetime.now(timezone.utc).isoformat(),
                            origin=origin,
                            validated=False,
                        )
                        get_store().add(memory)
                        result["stored_in_db"] = True
                        logger.info(f"  -> Stored raw chunks in vector DB (validated=False)")
                except Exception as e:
                    logger.error(f"Failed to store raw chunks: {e}")

            # Write validation marker (idempotency key)
            _write_validation_marker(jsonl_path, validation, final_content)

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        logger.exception(f"Error processing {jsonl_path.name}: {e}")

    return result


def run_sleep_cycle(
    chats_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Run the sleep cycle: summarize, validate, and store all pending sessions.

    Args:
        chats_dir: Directory containing sealed_audit_*.jsonl files
        dry_run: If True, scan and report but don't write to vector DB

    Returns:
        Dict with detailed stats.
    """
    chats_dir = chats_dir or _get_chats_dir()

    stats = {
        "total_scanned": 0,
        "already_validated": 0,
        "processed": 0,
        "approved": 0,
        "approved_stripped": 0,
        "fallback_raw_chunks": 0,
        "failed": 0,
        "stored_in_db": 0,
        "bootstrap_pruned": 0,
        "results": [],
    }

    if not chats_dir.exists():
        logger.error(f"Chats directory does not exist: {chats_dir}")
        return stats

    all_jsonl = list(chats_dir.glob("sealed_audit_*.jsonl"))
    stats["total_scanned"] = len(all_jsonl)

    for jsonl_path in all_jsonl:
        validated_path = jsonl_path.with_suffix(".validated.json")

        if validated_path.exists():
            stats["already_validated"] += 1
            logger.debug(f"Skipping (already validated): {jsonl_path.name}")
            continue

        result = _process_session(jsonl_path, dry_run=dry_run)
        stats["results"].append(result)
        stats["processed"] += 1

        # Update stats based on result
        status = result.get("status", "unknown")
        if status == "approved":
            stats["approved"] += 1
            if result.get("stored_in_db"):
                stats["stored_in_db"] += 1
        elif status == "approved_stripped":
            stats["approved_stripped"] += 1
            if result.get("stored_in_db"):
                stats["stored_in_db"] += 1
        elif status == "approved_after_re_summarize":
            stats["approved"] += 1
            if result.get("stored_in_db"):
                stats["stored_in_db"] += 1
        elif status == "fallback_raw_chunks":
            stats["fallback_raw_chunks"] += 1
            if result.get("stored_in_db"):
                stats["stored_in_db"] += 1
        elif status == "failed":
            stats["failed"] += 1

    # Bootstrap pruning: remove bootstrap memories if live count exceeds threshold
    if os.environ.get('BOOTSTRAP_PRUNE_ON_SLEEP') == '1' and not dry_run:
        logger.info("Checking bootstrap prune threshold...")
        stats["bootstrap_pruned"] = prune_bootstrap()

    return stats


def print_stats(stats: dict):
    """Pretty-print sleep cycle stats."""
    print(f"\nSleep Cycle Report ({datetime.now().isoformat()})")
    print("=" * 50)
    print(f"Total scanned:      {stats['total_scanned']}")
    print(f"Already validated:  {stats['already_validated']}")
    print(f"Processed this run: {stats['processed']}")
    print(f"  Approved:         {stats['approved']}")
    print(f"  Approved stripped:{stats['approved_stripped']}")
    print(f"  Fallback chunks:  {stats['fallback_raw_chunks']}")
    print(f"  Failed:           {stats['failed']}")
    print(f"Stored in vector DB: {stats['stored_in_db']}")
    if stats.get('bootstrap_pruned', 0) > 0:
        print(f"Bootstrap pruned:    {stats['bootstrap_pruned']}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Sleep cycle: summarize, validate, and store session logs"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report but don't write to vector DB",
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
