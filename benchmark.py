import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration & Setup
# ---------------------------------------------------------------------------
load_dotenv()

# Configure professional logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Global configuration
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080").rstrip('/')

# Path definitions using pathlib for cleaner path manipulation
AGENT_DIR = Path("agent-core")
STATE_FILE = AGENT_DIR / "state" / "messages.json"
STREAM_FILE = AGENT_DIR / "state" / "stream.json"

RESULTS_DIR = Path("eval-dashboard/src/data")
DIFFS_DIR = RESULTS_DIR / "diffs"
CHATS_DIR = RESULTS_DIR / "chats"


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def _run_command(cmd: List[str], cwd: Optional[Path] = None) -> str:
    """Helper to run shell commands and return stdout, reducing boilerplate."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, cwd=cwd
        )
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Command execution failed: {' '.join(cmd)} - {e}")
        return ""


def check_llm_health() -> bool:
    """Hits the local LLM /health endpoint to ensure it's up."""
    health_url = f"{LLM_BASE_URL}/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


# ---------------------------------------------------------------------------
# State & File Management
# ---------------------------------------------------------------------------
def clear_state() -> None:
    """Wipes the agent's memory to ensure a pristine cold boot."""
    for file_path in (STATE_FILE, STREAM_FILE):
        if file_path.exists():
            file_path.unlink()


def save_chat_state(run_id: int, timestamp: str) -> None:
    """Preserves the review chat state for a completed run."""
    CHATS_DIR.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        shutil.copy2(STATE_FILE, CHATS_DIR / f"run{run_id}_{timestamp}_messages.json")

    if STREAM_FILE.exists():
        shutil.copy2(STREAM_FILE, CHATS_DIR / f"run{run_id}_{timestamp}_stream.json")


# ---------------------------------------------------------------------------
# Audit & Preview Logging
# ---------------------------------------------------------------------------
def _audit_preview(messages: Any, max_chars: int = 500) -> List[Dict[str, Any]] | Dict[str, Any]:
    """Generates a condensed preview of message history for the audit log."""
    if not isinstance(messages, list):
        return {
            "format": "non-array",
            "type": type(messages).__name__,
            "keys": list(messages.keys()) if isinstance(messages, dict) else None,
        }

    preview: List[Dict[str, Any]] = []
    total_chars = 0

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        
        entry = {
            "role": msg.get("role", "unknown"),
            "content_len": len(content),
            "tool_calls_count": len(tool_calls),
        }

        if content:
            entry["content_preview"] = content[:100]
        
        if tool_calls:
            entry["tools"] = [
                tc.get("function", {}).get("name", "?")
                for tc in tool_calls if isinstance(tc, dict)
            ]
            
        preview.append(entry)
        total_chars += len(content)
        
        if total_chars > max_chars:
            break

    return preview


def sealed_audit_watcher(audit_path: Path, stop_event: threading.Event, poll_interval: float = 0.5) -> None:
    """Host-side tailer: appends a sealed-audit record when state updates."""
    last_mtime = 0.0

    while not stop_event.is_set():
        try:
            if STATE_FILE.exists():
                mt = STATE_FILE.stat().st_mtime
                if mt > last_mtime:
                    last_mtime = mt
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        messages = json.load(f)

                    record = {
                        "timestamp": datetime.now().isoformat(),
                        "messages_count": len(messages) if isinstance(messages, list) else None,
                        "messages_preview": _audit_preview(messages),
                    }

                    with open(audit_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

        except (json.JSONDecodeError, OSError):
            pass  # Fail silently to avoid crashing the watcher thread
            
        stop_event.wait(poll_interval)


# ---------------------------------------------------------------------------
# Git Operations
# ---------------------------------------------------------------------------
def git_restore() -> None:
    """Restores agent-core/ to the last committed (pristine) state."""
    _run_command(["git", "checkout", "--", str(AGENT_DIR) + "/"])


def git_stash_initial() -> bool:
    """Stash uncommitted work before benchmark runs to preserve it."""
    stdout = _run_command(["git", "status", "--porcelain", str(AGENT_DIR) + "/"])
    
    if stdout:
        logger.warning(f"Uncommitted changes detected in {AGENT_DIR}/")
        logger.info("Stashing changes with 'git stash -u' to preserve your work...")
        _run_command(["git", "stash", "push", "-u", "-m", "benchmark-preserve-work", str(AGENT_DIR) + "/"])
        return True
    return False


def git_restore_final(has_stash: bool) -> None:
    """After all runs, pop the stash to restore any stashed work."""
    if has_stash:
        logger.info("Restoring stashed changes...")
        _run_command(["git", "stash", "pop"])


def git_diff_stat() -> List[Dict[str, str]]:
    """Returns files the agent modified relative to the pristine commit."""
    stdout = _run_command(["git", "diff", "--name-status", str(AGENT_DIR) + "/"])
    changes = []
    
    for line in stdout.splitlines():
        if line.strip():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                changes.append({"status": parts[0], "file": parts[1]})
    return changes


def git_diff_content() -> str:
    """Returns the full unified diff of agent-core/ changes."""
    return _run_command(["git", "diff", str(AGENT_DIR) + "/"])


def detect_workspace_changes() -> List[Dict[str, str]]:
    """Returns lists of files created/modified in workspace/ during a run."""
    stdout = _run_command(["git", "status", "--porcelain", "workspace/"])
    created = []
    
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            status, filepath = line[:2].strip(), line[3:]
            if filepath != "workspace/.gitkeep":
                created.append({"status": status, "file": filepath})
    return created


# ---------------------------------------------------------------------------
# Metadata & Analysis
# ---------------------------------------------------------------------------
def collect_experiment_metadata() -> Dict[str, Any]:
    """Gathers environmental and file-based metadata for the experiment."""
    
    # Process model name safely
    raw_model = os.getenv("LLM_MODEL", "")
    model_name = raw_model[len("openai/"):] if raw_model.startswith("openai/") else raw_model

    metadata: Dict[str, Any] = {
        "independent_variables": {
            "system_prompt": None,
            "temperature": float(os.getenv("LLM_TEMPERATURE")) if os.getenv("LLM_TEMPERATURE") else None,
            "model": model_name or None,
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS")) if os.getenv("LLM_MAX_TOKENS") else None,
            "error_inject_role": os.getenv("ERROR_INJECT_ROLE", "tool").lower()
        },
        "constants": {
            "context_window": int(os.getenv("LLM_CTX_SIZE")) if os.getenv("LLM_CTX_SIZE") else None,
            "gpu_layers": int(os.getenv("LLM_GPU_LAYERS")) if os.getenv("LLM_GPU_LAYERS") else None,
            "max_generation": int(os.getenv("LLM_MAX_GENERATION")) if os.getenv("LLM_MAX_GENERATION") else None,
            "quantization": None
        }
    }

    # Agent-specific file parsing (fallback/override)
    re_cur_path = AGENT_DIR / "re_cur.py"
    if re_cur_path.exists():
        try:
            content = re_cur_path.read_text(encoding="utf-8")
            if match := re.search(r'SYSTEM_PROMPT\s*=\s*(["\'])(.*?)\1', content):
                metadata["independent_variables"]["system_prompt"] = match.group(2)
        except Exception as e:
            logger.debug(f"Failed to parse system prompt: {e}")

    # Extract Quantization from Model Name
    if model_name and (q_match := re.search(r'(Q\d+_K_\w+|Q\d+)', model_name)):
        metadata["constants"]["quantization"] = q_match.group(1)

    return metadata


def run_analyzer(sealed_audit_path: Optional[Path] = None) -> Dict[str, Any]:
    """Invokes the Phase 1 analyzer to grade the run."""
    cmd = ["python3", "analyze_session.py"]
    if sealed_audit_path:
        cmd.extend(["--sealed-audit", str(sealed_audit_path)])
        
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
            
    logger.error(f"Analyzer failed. Output: {result.stdout}")
    return {"error": "Analyzer failed", "stdout": result.stdout}


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
def main(num_runs: int, max_runtime: int) -> None:
    # Ensure directories exist
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DIFFS_DIR.mkdir(parents=True, exist_ok=True)
    CHATS_DIR.mkdir(parents=True, exist_ok=True)

    if not check_llm_health():
        logger.critical(f"LLM server is not reachable at {LLM_BASE_URL}/health")
        sys.exit(1)

    metadata = collect_experiment_metadata()
    logger.info(f"Loaded configuration for model: {metadata['independent_variables']['model']}")
    logger.info("Benchmark ready to proceed...")
    
    # ... [Rest of script execution logic] ...

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LLM Agent Benchmarks")
    parser.add_argument("--runs", type=int, default=1, help="Number of benchmark iterations to run")
    parser.add_argument("--max-runtime", type=int, default=900, help="Max runtime in seconds")
    
    args = parser.parse_args()
    main(args.runs, args.max_runtime)