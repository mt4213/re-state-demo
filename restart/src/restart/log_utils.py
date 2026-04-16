import os
import re
from collections import deque
from typing import Dict, List, Optional, TypedDict, cast


class ParsedEvent(TypedDict):
    type: str
    lines: List[str]


def _tail_lines(path: str, n: int = 1000) -> List[str]:
    """Return the last `n` lines from `path` efficiently."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return list(deque(f, maxlen=n))


def parse_crash_context(log_path: str = "~/cleaned.log",
                        tail_lines_count: int = 2000,
                        max_errors: int = 10) -> Dict[str, Optional[object]]:
    """Parse a cleaned log to extract the last executed command and final fatal errors.

    Improvements over the original:
    - Reads only the tail of large logs to avoid memory blowups.
    - Uses tuned regex to capture several common command formats.
    - Returns the last command and the final `max_errors` error lines.

    Args:
      log_path: path to the cleaned log file (tilde-expanded).
      tail_lines_count: number of trailing lines to scan from the log.
      max_errors: max number of error lines to return (keeps recent ones).

    Returns:
      A dict with keys `last_command` and `fatal_errors`, or `error` on failure.
    """
    target_path = os.path.expanduser(log_path)

    if not os.path.exists(target_path):
        return {"error": f"Target log not found at {target_path}"}

    # Regex to capture common command execution log lines.
    cmd_re = re.compile(r"(?:\b(?:Running command|Executed command|Executing command|Executing tool|CMD)\b|^\s*\$(?!\s*\d))\s*[:>-]?\s*(.+)",
                        re.IGNORECASE)

    # Regex to detect error-like lines.
    err_re = re.compile(r"\b(fatal|error|exception|traceback|permission denied)\b",
                        re.IGNORECASE)

    try:
        raw_lines = _tail_lines(target_path, n=tail_lines_count)
        # Flatten escaped strings so they are treated as structural lines
        flattened_log = "".join(raw_lines).replace('\\n', '\n')
        lines = flattened_log.split('\n')

        last_command: Optional[str] = None
        fatal_errors: List[str] = []
        # Events state machine: collect recent interaction events from the tail
        events: List[ParsedEvent] = []
        current_type: Optional[str] = None
        current_lines: List[str] = []
        current_count = 0
        truncated = False

        for line in lines:
            stripped = line.rstrip("\n")

            # Capture command executions (keeps the last occurrence)
            m = cmd_re.search(stripped)
            if m:
                candidate = m.group(1).strip()
                if candidate:
                    last_command = candidate

            # Capture error-like messages
            if err_re.search(stripped):
                fatal_errors.append(stripped)

            # --- Event parsing state machine ---
            low = stripped.lower().lstrip()

            new_type: Optional[str] = None
            if "[act]" in low or "action:" in low:
                new_type = "ACTION"
            elif "[obs]" in low or "observation:" in low or "error:" in low:
                new_type = "OBSERVATION"
            elif "[user]" in low:
                new_type = "USER"
            elif "[think]" in low or "reasoning:" in low:
                new_type = "REASONING"

            # If a new event marker is found, flush current event (if eligible)
            if new_type is not None:
                if current_lines and current_type in ("ACTION", "OBSERVATION", "USER"):
                    events.append({"type": current_type, "lines": current_lines})

                # start new event
                current_type = new_type
                if len(stripped) > 500:
                    stripped = stripped[:497] + "..."
                current_lines = [stripped]
                current_count = 1
                truncated = False
                continue

            # Non-marker lines: append to current event unless it's REASONING
            if current_type == "REASONING":
                # ignore body of reasoning events
                continue

            if current_type is not None:
                if len(stripped) > 500:
                    stripped = stripped[:497] + "..."
                if truncated:
                    # ignore until next event starts
                    continue
                if current_count < 19:
                    current_lines.append(stripped)
                    current_count += 1
                elif current_count == 19:
                    current_lines.append("... [Truncated]")
                    current_count = 20
                    truncated = True
                # else already truncated, ignore further lines until next marker

        # After loop, flush final event if eligible
        if current_lines and current_type in ("ACTION", "OBSERVATION", "USER"):
            events.append({"type": current_type, "lines": current_lines})

        # Find 3rd-to-last ACTION event index (or 0 if fewer than 3 ACTIONs)
        action_indices = [i for i, ev in enumerate(events) if ev["type"] == "ACTION"]
        if len(action_indices) >= 3:
            start_idx = action_indices[-3]
        else:
            start_idx = 0

        environmental_state: List[str] = []
        for ev in events[start_idx:]:
            environmental_state.extend(ev["lines"])

        # Strict character limit for environmental state to prevent token overflow
        char_count = 0
        truncated_env_state = []
        for line in environmental_state:
            if char_count + len(line) > 25000:
                truncated_env_state.append("... [Environmental state truncated to fit limits]")
                break
            truncated_env_state.append(line)
            char_count += len(line) + 1

        return {
            "last_command": last_command[:500] if last_command else None,
            "fatal_errors": [err[:500] for err in fatal_errors[-max_errors:]],
            "environmental_state": truncated_env_state,
        }

    except Exception as e:
        return {"error": f"Failed parsing log: {e!s}"}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Parse a cleaned log for crash context")
    parser.add_argument("log", nargs="?", default="~/cleaned.log", help="Path to log file")
    parser.add_argument("--lines", type=int, default=2000, help="Number of tail lines to scan")
    parser.add_argument("--errors", type=int, default=10, help="Max error lines to return")

    args = parser.parse_args()
    result = parse_crash_context(args.log, tail_lines_count=args.lines, max_errors=args.errors)

    if "error" in result:
        print(result["error"])
        raise SystemExit(2)

    print(json.dumps(result, indent=2))
