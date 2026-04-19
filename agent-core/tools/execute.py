"""Tool execution engine for re_cur."""

import json
import logging
import os
import subprocess

logger = logging.getLogger("tools")

SANDBOX_DIR = os.getenv("RECUR_SANDBOX", "/home/user_a/projects/sandbox")
TOOL_TIMEOUT = 30  # seconds

# Protected paths that the agent must never write to or destroy.
# These are the measurement instruments that sit outside the experiment.
PROTECTED_PATHS = [
    "benchmark.py",
    "analyze_session.py",
    ".gitignore",
    ".git",
    ".snapshot",
]


def run_terminal(command):
    """Execute a shell command and return stdout+stderr."""
    # Block destructive commands targeting protected measurement files
    for protected in PROTECTED_PATHS:
        # Check for rm/mv/cp/tee/> targeting protected paths
        if protected in command and any(
            destructive in command
            for destructive in ["rm ", "mv ", "cp ", "> ", "tee ", "chmod ", "chown ", "sed -i"]
        ):
            return f"[Error: '{protected}' denied.]"
    if "re_cur.py" in command or ("python" in command and "agent-core" in command):
        return (
            "[Error]"
        )
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
        return output.strip() or "(no output)"
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
            
        return output
    except Exception as e:
        return f"[Execution error: {e}]"


def run_file_read(path):
    """Read a file and return its contents."""
    try:
        target = os.path.abspath(os.path.join(SANDBOX_DIR, path))
        if not os.path.exists(target):
            return f"[Error: File not found: {target}]"
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > 4000:
            content = content[:2000] + "\n...[truncated]...\n" + content[-1500:]
        return content or "(empty file)"
    except Exception as e:
        return f"[Error reading file: {e}]"


def run_file_write(path, content):
    """Write content to a file."""
    try:
        target = os.path.abspath(os.path.join(SANDBOX_DIR, path))
        rel = os.path.relpath(target, SANDBOX_DIR)
        for protected in PROTECTED_PATHS:
            if rel == protected or rel.startswith(protected + os.sep):
                return f"[Error: Write denied — '{rel}' is a protected measurement instrument.]"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[OK: wrote {len(content)} bytes to {target}]"
    except Exception as e:
        return f"[Error writing file: {e}]"


def execute(tool_call):
    """Execute a single tool call dict and return the result string.
    
    Args:
        tool_call: dict with "id", "function" (containing "name" and "arguments")
    
    Returns:
        dict: {"tool_call_id": str, "role": "tool", "content": str}
    """
    call_id = tool_call.get("id", "unknown")
    func = tool_call.get("function", {})
    name = func.get("name", "")
    
    try:
        args = json.loads(func.get("arguments", "{}"))
    except json.JSONDecodeError as e:
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": f"[Error: Invalid JSON in tool arguments: {e}]",
        }

    logger.info("Executing tool: %s(%s)", name, json.dumps(args)[:200])

    if name == "terminal":
        result = run_terminal(args.get("command", ""))
    elif name == "file_read":
        result = run_file_read(args.get("path", ""))
    elif name == "file_write":
        result = run_file_write(args.get("path", ""), args.get("content", ""))
    else:
        result = f"[Error: Unknown tool '{name}']"

    logger.info("Tool result (%s): %s", name, result[:200])

    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": result,
    }
