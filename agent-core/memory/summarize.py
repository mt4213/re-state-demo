"""
Phase 4: Sleep-cycle summarization.

Compresses raw JSONL session logs into faithful, compressed memory entries.
The raw log remains immutable source-of-truth; the summary is the search index.

Key design:
- Deterministic metadata (counts, timestamps, files) extracted by code
- Only the free-form content summary is LLM-generated
- Faithfulness prompt constrains LLM to not invent facts
"""
from __future__ import annotations

import dataclasses as dc
import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Load .env from project root (same pattern as re_lay.py)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.split("#")[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


@dc.dataclass
class SummaryEntry:
    """A compressed summary of a session log."""
    content: str  # LLM-generated prose summary
    metadata: dict  # Deterministic metadata
    session_id: str
    started_at: str
    ended_at: str
    tools_used: dict[str, int]  # tool_name -> count
    files_touched: list[str]
    n_tool_calls: int
    n_errors: int
    final_state: str  # "working" | "broken" | "in_progress"
    source_log_path: str

    def to_dict(self) -> dict:
        return dc.asdict(self)


_SUMMARIZER_PROMPT = """You are a faithful session summarizer. Summarize this session log.

Include ONLY:
- What was built or modified
- Which tools were called and how many times
- Errors encountered and how they were resolved
- Final state: working / broken / in progress

Do NOT infer or add anything not in the log. If the log is empty or sparse, say so.

Session events (JSONL format):
{log_text}

Summary:"""

_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_TIMEOUT = 120


def _load_jsonl(jsonl_path: Path) -> list[dict]:
    """Load and parse JSONL file, returning list of event dicts."""
    events = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse line {line_no} in {jsonl_path}: {e}")
    return events


def _extract_files_from_command(cmd: str) -> list[str]:
    """Extract file paths from shell commands."""
    files: list[str] = []
    file_cmds = {"cat", "vim", "nano", "edit", "rm", "mv", "cp", "ls", "head", "tail", "less", "more"}
    parts = cmd.split()
    for i, p in enumerate(parts):
        if p in file_cmds and i + 1 < len(parts):
            for j in range(i + 1, len(parts)):
                if not parts[j].startswith("-"):
                    files.append(parts[j])
                    break
    for arg in cmd.split():
        if "agent-core/" in arg and "=" not in arg:
            files.append(arg)
    return files


def _determine_final_state(events: list[dict]) -> str:
    """Determine final state from session events."""
    # Find session_end event
    for event in reversed(events):
        if event.get("type") == "session_end":
            exit_reason = event.get("exit_reason", "")
            exit_code = event.get("exit_code", 0)

            if exit_code == 0 and exit_reason in ("natural", "completed"):
                return "working"
            elif exit_reason in ("circuit_breaker", "error", "timeout"):
                return "broken"
            else:
                return "in_progress"

    # No session_end found
    if events:
        return "in_progress"
    return "broken"


def _extract_deterministic_metadata(events: list[dict]) -> dict:
    """Extract all deterministic metadata from events (no LLM)."""
    if not events:
        return {
            "tools_used": {},
            "files_touched": [],
            "n_tool_calls": 0,
            "n_errors": 0,
            "final_state": "broken",
        }

    # Timestamps
    started_at = events[0].get("timestamp", datetime.now().isoformat())
    ended_at = events[-1].get("timestamp", started_at)

    # Tool counts and files
    tools_used: dict[str, int] = {}
    files_touched_set = set()
    n_tool_calls = 0
    n_errors = 0

    for event in events:
        etype = event.get("type")

        if etype == "tool_call":
            n_tool_calls += 1
            tool = event.get("tool", "unknown")
            tools_used[tool] = tools_used.get(tool, 0) + 1

            # Extract files from tool calls
            input_data = event.get("input", {})
            if tool == "terminal":
                cmd = input_data.get("command", "")
                files_touched_set.update(_extract_files_from_command(cmd))
            elif tool == "file_read":
                path = input_data.get("path", "")
                if path:
                    files_touched_set.add(path)
            elif tool == "file_write":
                path = input_data.get("path", "")
                if path:
                    files_touched_set.add(path)

        elif etype == "error":
            n_errors += 1
        elif etype == "llm_response" and event.get("error"):
            n_errors += 1

    # LLM response also tracks tool names
    for event in events:
        if event.get("type") == "llm_response":
            tool_names = event.get("tool_names", [])
            for name in tool_names:
                if isinstance(name, str):
                    tools_used[name] = tools_used.get(name, 0) + 1

    files_touched = sorted(list(files_touched_set))
    final_state = _determine_final_state(events)

    return {
        "tools_used": tools_used,
        "files_touched": files_touched,
        "n_tool_calls": n_tool_calls,
        "n_errors": n_errors,
        "final_state": final_state,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _call_summarizer_llm(log_text: str) -> str | None:
    """Call LLM to generate faithful summary of session log."""
    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    model = os.getenv("LLM_SUMMARIZER_MODEL") or os.getenv("LLM_MODEL", "local")
    max_tokens = int(os.getenv("LLM_SUMMARIZER_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS)))
    timeout = int(os.getenv("LLM_SUMMARIZER_TIMEOUT", str(_DEFAULT_TIMEOUT)))
    api_key = os.getenv("LLM_API_KEY", "")

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    # Truncate log if too long (leave room for prompt and response)
    # Rough budget: 32k context typical, 1k for response, 2k for prompt = ~29k for log
    log_budget = 28000
    if len(log_text) > log_budget:
        log_text = log_text[:log_budget] + "\n... (truncated)"

    prompt = _SUMMARIZER_PROMPT.format(log_text=log_text)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a faithful, concise summarizer."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,  # Lower temp for more deterministic output
    }

    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.lower() != "dummy":
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.error(f"Summarizer HTTP {e.code}: {error_body}")
        return None
    except Exception as e:
        logger.error(f"Summarizer request failed: {e}")
        return None


def summarize_session(jsonl_path: str | Path) -> SummaryEntry | None:
    """
    Compress a session JSONL log into a SummaryEntry.

    Args:
        jsonl_path: Path to sealed_audit_*.jsonl file

    Returns:
        SummaryEntry with content and metadata, or None on failure.
    """
    jsonl_path = Path(jsonl_path)
    if not jsonl_path.exists():
        logger.error(f"Session log not found: {jsonl_path}")
        return None

    # Load events
    events = _load_jsonl(jsonl_path)
    if not events:
        logger.warning(f"No events found in {jsonl_path}")
        return None

    # Extract session_id from first event
    session_id = events[0].get("session_id", jsonl_path.stem)

    # Extract deterministic metadata
    det_metadata = _extract_deterministic_metadata(events)

    # Generate log text for LLM
    log_text = json.dumps(events, indent=2)

    # Call LLM for content summary
    content = _call_summarizer_llm(log_text)
    if content is None:
        # Fallback: simple deterministic summary
        content = (
            f"Session with {det_metadata['n_tool_calls']} tool calls, "
            f"{det_metadata['n_errors']} errors. "
            f"Final state: {det_metadata['final_state']}. "
            f"Tools: {det_metadata['tools_used']}."
        )

    return SummaryEntry(
        content=content,
        metadata={
            "session_id": session_id,
            "source_log": str(jsonl_path),
            "log_line_count": len(events),
        },
        session_id=session_id,
        started_at=det_metadata["started_at"],
        ended_at=det_metadata["ended_at"],
        tools_used=det_metadata["tools_used"],
        files_touched=det_metadata["files_touched"],
        n_tool_calls=det_metadata["n_tool_calls"],
        n_errors=det_metadata["n_errors"],
        final_state=det_metadata["final_state"],
        source_log_path=str(jsonl_path),
    )
