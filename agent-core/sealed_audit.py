"""Sealed Audit Logger — writes to eval_results/ from OUTSIDE agent's control.

This module is imported by re_cur.py but writes to a path that is NOT mounted
inside the Docker container. This ensures the audit log is immutable and cannot
be modified by the agent, even if it modifies persist_state().

Phase 1 Schema: Granular event-level logging with types:
  - session_start: Marks the beginning of an agent session
  - session_end: Marks the end of an agent session with exit reason
  - tool_call: Individual tool execution with timing and results
  - llm_response: LLM generation events (reasoning, content, tool_calls)
  - error: Error events (LLM errors, parse errors, circuit breakers)

Location: agent-core/ is mounted in Docker
          eval_results/ is NOT mounted — lives on host filesystem only
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional, Any, Dict

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


def _write_event(event: Dict[str, Any]) -> None:
    """Write a single event record to the audit log.

    Args:
        event: Dictionary with at minimum: timestamp, session_id, type
    """
    try:
        audit_path = _get_audit_path()
        with _lock:
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Cannot log here — might cause recursion
        # Just silently fail to not disrupt agent
        pass


def log_session_start(session_id: str, system_prompt: str) -> None:
    """Log the start of an agent session.

    Args:
        session_id: Unique identifier for this session
        system_prompt: The directive given to the agent
    """
    _write_event({
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "type": "session_start",
        "system_prompt_preview": system_prompt[:200] if system_prompt else "",
    })


def log_session_end(session_id: str, exit_reason: str, total_turns: int, exit_code: int) -> None:
    """Log the end of an agent session.

    Args:
        session_id: Unique identifier for this session
        exit_reason: Why the session ended (natural, circuit_breaker, error, etc.)
        total_turns: Number of iterations completed
        exit_code: Process exit code
    """
    _write_event({
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "type": "session_end",
        "exit_reason": exit_reason,
        "total_turns": total_turns,
        "exit_code": exit_code,
    })


def log_tool_call(session_id: str, tool_name: str, tool_input: Dict[str, Any],
                  output: str, duration_ms: int, exit_code: Optional[int] = None) -> None:
    """Log a tool execution event.

    Args:
        session_id: Unique identifier for this session
        tool_name: Name of the tool (terminal, file_read, file_write)
        tool_input: Arguments passed to the tool
        output: Result content
        duration_ms: Execution time in milliseconds
        exit_code: For terminal commands, the shell exit code
    """
    _write_event({
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "type": "tool_call",
        "tool": tool_name,
        "input": tool_input,
        "output": output,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
    })


def log_llm_response(session_id: str, turn: int, reasoning: Optional[str] = None,
                     content: Optional[str] = None, tool_calls: Optional[list] = None,
                     error: Optional[str] = None) -> None:
    """Log an LLM generation event.

    Args:
        session_id: Unique identifier for this session
        turn: Turn number in the session
        reasoning: Thinking/reasoning content (if present)
        content: Text content (if present)
        tool_calls: List of tool call objects (if present)
        error: Error message (if generation failed)
    """
    event = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "type": "llm_response",
        "turn": turn,
    }

    if reasoning:
        event["reasoning_preview"] = reasoning[:300]
    if content:
        event["content_preview"] = content[:300]
    if tool_calls:
        event["tool_calls_count"] = len(tool_calls)
        event["tool_names"] = [
            tc.get("function", {}).get("name", "?")
            for tc in tool_calls
            if isinstance(tc, dict)
        ]
    if error:
        event["error"] = error

    _write_event(event)


def log_error(session_id: str, error_type: str, message: str,
              context: Optional[Dict[str, Any]] = None) -> None:
    """Log an error event.

    Args:
        session_id: Unique identifier for this session
        error_type: Category of error (llm_error, parse_error, circuit_breaker, etc.)
        message: Error message
        context: Additional context (turn number, retry count, etc.)
    """
    event = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "type": "error",
        "error_type": error_type,
        "message": message,
    }

    if context:
        event["context"] = context

    _write_event(event)


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
