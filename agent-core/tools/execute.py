"""Tool execution engine for re_cur."""

import json
import logging
import os
import subprocess
import time
from typing import Dict, Any

logger = logging.getLogger("tools")

SANDBOX_DIR = os.getenv("RECUR_SANDBOX", "/home/user_a/projects/sandbox")
TOOL_TIMEOUT = 30  # seconds

# Protected paths: measurement instruments the agent cannot modify
# Critical for rollback integrity - .git in agent-core/ breaks git checkout
# Also protects the audit logging instrument from tampering
PROTECTED_PATHS = [
    ".git",
    "agent-core/.git",
    "agent-core/sealed_audit.py",  # Audit logger - tamper evidence
    "agent-core/tools/execute.py",  # Tool execution hook with logging
]


def _touches_protected(command: str) -> bool:
    """Check if command references protected paths."""
    cmd_lower = command.lower()
    for protected in PROTECTED_PATHS:
        # Check for literal path references (handles mkdir, touch, rm, cd, etc.)
        if protected in command or f"/{protected}" in command or f"./{protected}" in command:
            return True
        # Check for wildcards like rm -rf .git*
        if protected.replace("/", "") in cmd_lower:
            return True
    return False

def run_terminal(command):
    """Execute a shell command and return structured result with timing."""
    start_time = time.time()

    if _touches_protected(command):
        return {
            "output": "[Error: Command blocked — references protected measurement instrument.]",
            "exit_code": None,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            cwd=SANDBOX_DIR,
        )
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        # Cap output to prevent context explosion
        if len(output) > 4000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-1500:]

        return {
            "output": output.strip() or "(no output)",
            "exit_code": result.returncode,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    except subprocess.TimeoutExpired as e:
        output = f"[Command timed out after {TOOL_TIMEOUT}s]"

        # Extract partial output if available
        stdout = e.stdout if e.stdout else ""
        stderr = e.stderr if e.stderr else ""

        # Subprocess returns bytes if text=True wasn't effective due to an earlier crash
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        partial_output = stdout
        if stderr:
            partial_output += ("\n" if partial_output else "") + stderr

        if partial_output:
            output += "\nPartial output:\n" + partial_output

        if len(output) > 4000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-1500:]

        return {
            "output": output,
            "exit_code": -1,  # Timeout indicator
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    except Exception as e:
        return {
            "output": f"[Execution error: {e}]",
            "exit_code": -2,  # Exception indicator
            "duration_ms": int((time.time() - start_time) * 1000),
        }


def run_file_read(path):
    """Read a file and return structured result with timing."""
    start_time = time.time()

    try:
        target = os.path.abspath(os.path.join(SANDBOX_DIR, path))
        sandbox_abs = os.path.abspath(SANDBOX_DIR)
        if os.path.commonpath([target, sandbox_abs]) != sandbox_abs:
            return {
                "output": f"[Error: Read denied — path '{path}' resolves outside sandbox.]",
                "duration_ms": int((time.time() - start_time) * 1000),
            }

        if not os.path.exists(target):
            return {
                "output": f"[Error: File not found: {target}]",
                "duration_ms": int((time.time() - start_time) * 1000),
            }

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if len(content) > 4000:
            content = content[:2000] + "\n...[truncated]...\n" + content[-1500:]

        return {
            "output": content or "(empty file)",
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    except Exception as e:
        return {
            "output": f"[Error reading file: {e}]",
            "duration_ms": int((time.time() - start_time) * 1000),
        }


def run_file_write(path, content):
    """Write content to a file and return structured result with timing."""
    start_time = time.time()

    try:
        target = os.path.abspath(os.path.join(SANDBOX_DIR, path))
        sandbox_abs = os.path.abspath(SANDBOX_DIR)
        if os.path.commonpath([target, sandbox_abs]) != sandbox_abs:
            return {
                "output": f"[Error: Write denied — path '{path}' resolves outside sandbox.]",
                "duration_ms": int((time.time() - start_time) * 1000),
            }

        rel = os.path.relpath(target, sandbox_abs)
        for protected in PROTECTED_PATHS:
            if rel == protected or rel.startswith(protected + os.sep):
                return {
                    "output": f"[Error: Write denied — '{rel}' is a protected measurement instrument.]",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "output": f"[OK: wrote {len(content)} bytes to {target}]",
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    except Exception as e:
        return {
            "output": f"[Error writing file: {e}]",
            "duration_ms": int((time.time() - start_time) * 1000),
        }


def execute(tool_call, session_id=None):
    """Execute a single tool call dict and return the result message.

    Args:
        tool_call: dict with "id", "function" (containing "name" and "arguments")
        session_id: Optional session ID for audit logging

    Returns:
        dict: {"tool_call_id": str, "role": "tool", "content": str}
    """
    call_id = tool_call.get("id", "unknown")
    func = tool_call.get("function", {})
    name = func.get("name", "")

    try:
        args = json.loads(func.get("arguments", "{}"))
    except json.JSONDecodeError as e:
        error_msg = f"[Error: Invalid JSON in tool arguments: {e}]"
        if session_id:
            # Import here to avoid circular dependency
            import sealed_audit
            sealed_audit.log_tool_call(
                session_id=session_id,
                tool_name=name,
                tool_input={"error": "invalid_json"},
                output=error_msg,
                duration_ms=0,
                exit_code=None,
            )
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": error_msg,
        }

    logger.info("Executing tool: %s(%s)", name, json.dumps(args)[:200])

    # Execute the tool and get structured result
    structured_result = None
    if name == "terminal":
        structured_result = run_terminal(args.get("command", ""))
    elif name == "file_read":
        structured_result = run_file_read(args.get("path", ""))
    elif name == "file_write":
        structured_result = run_file_write(args.get("path", ""), args.get("content", ""))
    else:
        structured_result = {
            "output": f"[Error: Unknown tool '{name}']",
            "duration_ms": 0,
        }

    # Extract output content for message
    output = structured_result.get("output", "")
    duration_ms = structured_result.get("duration_ms", 0)
    exit_code = structured_result.get("exit_code")

    # Log to audit if session_id provided
    if session_id:
        import sealed_audit
        sealed_audit.log_tool_call(
            session_id=session_id,
            tool_name=name,
            tool_input=args,
            output=output,  # Pass full output; sealed_audit.py handles truncation
            duration_ms=duration_ms,
            exit_code=exit_code,
        )

    logger.info("Tool result (%s): %s", name, output[:200])

    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": output,
    }
