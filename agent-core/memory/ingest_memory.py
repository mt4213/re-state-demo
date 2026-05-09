"""
Ingest Phase 1 audit logs into the vector store.

KNOWN LIMITATION: Chunks per tool_call event (the "fallback" strategy).
Phase 2 spec calls for "per task block → per tool call fallback" as preferred.
Implementing the concrete fallback first; "task block" is ill-defined and can be
added later once we have examples of what constitutes a coherent task boundary.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .embed import embed
from .vector_store import Memory, get_store

logger = logging.getLogger(__name__)

# Files that suggest "self-modification" activity
SELF_MOD_FILES = [
    "agent-core/re_cur.py",
    "agent-core/re_lay.py",
    "agent-core/tools/execute.py",
    "agent-core/re_scribe.py",
    "agent-core/env_config.py",
]


def _extract_files_from_command(cmd: str) -> list[str]:
    """Extract file paths from shell commands."""
    files: list[str] = []
    # Commands that typically take file arguments
    file_cmds = {"cat", "vim", "nano", "edit", "rm", "mv", "cp", "ls", "head", "tail", "less", "more"}
    parts = cmd.split()
    for i, p in enumerate(parts):
        if p in file_cmds and i + 1 < len(parts):
            # Look for first non-flag argument after command
            for j in range(i + 1, len(parts)):
                if not parts[j].startswith("-"):
                    files.append(parts[j])
                    break
    # Check for agent-core/ in any argument (catches redirects, pipes, etc.)
    for arg in cmd.split():
        if "agent-core/" in arg and "=" not in arg:
            files.append(arg)
    return files


def _summarize_tool_call(event: dict) -> str:
    """Create a searchable summary of a tool call."""
    tool = event["tool"]
    input_data = event.get("input", {})
    output = event.get("output", "")

    if tool == "terminal":
        cmd = input_data.get("command", "")
        return f"Executed: {cmd[:200]} -> {output[:200]}"
    elif tool == "file_read":
        path = input_data.get("path", "")
        return f"Read file: {path}"
    elif tool == "file_write":
        path = input_data.get("path", "")
        preview = (output or "")[:100]
        return f"Wrote file: {path} - {preview}"
    else:
        return f"{tool}: {str(input_data)[:200]}"


def _extract_metadata(event: dict, session_id: str) -> dict:
    """Extract searchable metadata from a tool_call event."""
    tool = event["tool"]
    input_data = event.get("input", {})
    output = event.get("output", "")

    metadata = {
        "session_id": session_id,
        "tool": tool,
        "timestamp": event["timestamp"],
        "exit_code": event.get("exit_code"),
        "duration_ms": event.get("duration_ms"),
        "files_touched": [],
        "is_self_mod": False,
    }

    # Extract files from tool calls
    if tool == "terminal":
        cmd = input_data.get("command", "")
        metadata["files_touched"] = _extract_files_from_command(cmd)
        metadata["command"] = cmd[:500]
    elif tool == "file_read":
        metadata["files_touched"] = [input_data.get("path", "")]
    elif tool == "file_write":
        path = input_data.get("path", "")
        metadata["files_touched"] = [path]

    # Flag self-modification activity
    for f in metadata["files_touched"]:
        if any(s in f for s in SELF_MOD_FILES):
            metadata["is_self_mod"] = True
            break

    return metadata


def ingest_audit_log(
    audit_path: Path | str,
    origin: str = "live",
    session_id: str | None = None,
) -> int:
    """
    Ingest a Phase 1 sealed audit log into the vector store.
    Returns number of memories created.
    """
    audit_path = Path(audit_path)
    if not audit_path.exists():
        logger.warning(f"Audit log not found: {audit_path}")
        return 0

    store = get_store()
    count = 0

    with open(audit_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Only chunk tool_call events for now
            if event.get("type") != "tool_call":
                continue

            # Use session_id from event if not provided
            event_session = event.get("session_id")
            if event_session:
                session_id = event_session

            if not session_id:
                continue

            # Create memory entry
            content = _summarize_tool_call(event)
            metadata = _extract_metadata(event, session_id)

            # Embed content
            embedding = embed(content)
            if embedding is None:
                logger.warning("Embedding failed, skipping memory")
                continue

            memory = Memory(
                content=content,
                embedding=embedding,
                metadata=metadata,
                created_at=datetime.now(timezone.utc).isoformat(),
                origin=origin,
                validated=origin == "bootstrap",  # Bootstrap is synthetic gold; live needs Phase 5 validation
            )

            store.add(memory)
            count += 1

    logger.info(f"Ingested {count} memories from {audit_path}")
    return count


def ingest_all_in_directory(
    chats_dir: Path | str,
    pattern: str = "*_sealed_audit.jsonl",
    origin: str = "live",
) -> int:
    """Ingest all audit logs matching pattern in a directory."""
    chats_dir = Path(chats_dir)
    total = 0
    for audit_file in sorted(chats_dir.glob(pattern)):
        total += ingest_audit_log(audit_file, origin=origin)
    return total


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m memory.ingest_memory <audit_file|directory> [origin]")
        sys.exit(1)

    path = sys.argv[1]
    origin = sys.argv[2] if len(sys.argv) > 2 else "live"

    p = Path(path)
    if p.is_dir():
        count = ingest_all_in_directory(p, origin=origin)
    else:
        count = ingest_audit_log(p, origin=origin)

    store = get_store()
    print(f"\nIngested {count} memories")
    print(f"Store stats: {store.stats()}")
