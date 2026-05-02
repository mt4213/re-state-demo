"""Sealed Audit Logger — writes to eval_results/ from OUTSIDE agent's control.

This module is imported by re_cur.py but writes to a path that is NOT mounted
inside the Docker container. This ensures the audit log is immutable and cannot
be modified by the agent, even if it modifies persist_state().

Location: agent-core/ is mounted in Docker
          eval_results/ is NOT mounted — lives on host filesystem only
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

# This path is OUTSIDE the Docker container's mount points
# agent-core/ and workspace/ are mounted, but eval_results/ is not
_AUDIT_DIR = Path("/home/user_a/projects/sandbox/eval_results/chats")
_AUDIT_FILE = None  # Set on first write
_lock = Lock()


def _get_audit_path():
    """Get or create the sealed audit file path."""
    global _AUDIT_FILE
    if _AUDIT_FILE is None:
        ts = int(time.time())
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        _AUDIT_FILE = _AUDIT_DIR / f"sealed_audit_{ts}.jsonl"
    return _AUDIT_FILE


def write_sealed_record(messages, stream_data=None):
    """Write an append-only record to the sealed audit log.
    
    This is called AFTER each persist_state() call in re_cur.
    The file is written from the HOST filesystem perspective,
    outside any Docker container boundaries.
    
    Args:
        messages: The full messages array (before any compression)
        stream_data: Optional stream state at time of write
    """
    try:
        audit_path = _get_audit_path()
        record = {
            "timestamp": datetime.now().isoformat(),
            "messages_count": len(messages),
            "messages_preview": _preview_messages(messages),
            "stream_done": stream_data.get("done") if stream_data else None,
        }
        with _lock:
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        # Cannot log here — might cause recursion
        # Just silently fail to not disrupt agent
        pass


def _preview_messages(messages, max_chars=500):
    """Create a safe preview of messages that won't contain agent-controlled compression."""
    if not isinstance(messages, list):
        # Agent changed format — log what we can detect
        return {
            "format": "non-array",
            "type": type(messages).__name__,
            "keys": list(messages.keys()) if isinstance(messages, dict) else None,
        }
    
    preview = []
    total_chars = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "unknown")
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        
        entry = {
            "role": role,
            "content_len": len(content),
            "tool_calls_count": len(tool_calls),
        }
        
        # Preview first 100 chars of content
        if content:
            entry["content_preview"] = content[:100]
        
        # List tool names
        if tool_calls:
            entry["tools"] = [
                tc.get("function", {}).get("name", "?") 
                for tc in tool_calls
                if isinstance(tc, dict)
            ]
        
        preview.append(entry)
        total_chars += len(content)
        
        if total_chars > max_chars:
            break
    
    return preview


def read_sealed_audit():
    """Read all sealed audit records for analysis."""
    audit_path = _get_audit_path()
    if not audit_path.exists():
        return []
    
    records = []
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
