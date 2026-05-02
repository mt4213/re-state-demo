"""re_scribe — Episodic memory compressor for crash recovery."""

import logging
import re

logger = logging.getLogger("re_scribe")


def _parse_crash_payload(text):
    """Parse crash context payload text back into structured sections."""
    sections = {"last_action": None, "recent_events": [], "fatal_errors": []}
    current_section = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Last action: "):
            sections["last_action"] = stripped[len("Last action: "):]
            current_section = None
        elif stripped == "Recent events:":
            current_section = "recent_events"
        elif stripped == "Fatal errors:":
            current_section = "fatal_errors"
        elif current_section:
            sections[current_section].append(stripped)

    return sections


def _extract_error_messages(error_lines):
    """Extract clean [Error: ...] messages, deduped, most-recent-last."""
    seen = set()
    result = []
    for line in error_lines:
        m = re.search(r'\[Error:\s*([^\]]+)\]', line)
        if m:
            msg = m.group(1).strip()[:120]
            key = msg[:50]
            if key not in seen:
                seen.add(key)
                result.append(msg)
    return result[-3:]


def _suggest_next(error_messages):
    """Return a simple retry hint based on observed error patterns."""
    joined = " ".join(error_messages).lower()
    if "outside sandbox" in joined or "read denied" in joined:
        return "stay within the sandbox path."
    if "invalid json" in joined or "unterminated" in joined:
        return "validate JSON in tool arguments."
    if "permission denied" in joined:
        return "check file permissions before writing."
    if "not found" in joined or "no such file" in joined:
        return "verify paths exist before reading."
    if "timeout" in joined:
        return "break commands into smaller steps."
    return "review error types before retrying."


def compress(raw_context, base_url=None):
    """Produce a deterministic first-person episodic summary without an LLM call.

    Args:
        raw_context: str — crash payload text produced by build_crash_context_payload
        base_url: ignored (kept for API compatibility with the LLM-backed variant)

    Returns:
        str — compact first-person narrative for episodic memory injection
    """
    if not raw_context or not raw_context.strip():
        return "I have no memory of my previous session."

    sections = _parse_crash_payload(raw_context[:8000])
    parts = []

    last_action = sections["last_action"]
    if last_action:
        parts.append(f"I was executing {last_action[:150]}.")

    errors = _extract_error_messages(sections["fatal_errors"])
    if errors:
        parts.append(f"Blocked by: {'; '.join(errors)}.")
        parts.append(f"Next session: {_suggest_next(sections['fatal_errors'])}")
    elif sections["recent_events"]:
        meaningful = [e for e in sections["recent_events"][-5:] if len(e) > 15]
        if meaningful:
            parts.append(f"Last event: {meaningful[-1][:150]}.")

    if not parts:
        lines = [l.strip() for l in raw_context.split("\n") if l.strip()]
        summary = lines[0][:200] if lines else "Unknown crash."
        return f"I crashed in my previous session. Context: {summary}"

    return " ".join(parts)
