import os
import sys
import json
import subprocess
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime

STATE_FILE = "agent-core/state/messages.json"
AGENT_DIR = "agent-core"
RESULTS_DIR = "eval_results"
DIFFS_DIR = os.path.join(RESULTS_DIR, "diffs")


def check_llm_health():
    """Hits the local llama.cpp /health endpoint to ensure it's up."""
    try:
        req = urllib.request.Request("http://127.0.0.1:8080/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def clear_state():
    """Wipes the agent's memory to ensure a pristine cold boot."""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def git_restore():
    """Restores agent-core/ to the last committed (pristine) state via git."""
    subprocess.run(
        ["git", "checkout", "--", AGENT_DIR + "/"],
        capture_output=True, text=True
    )


def git_diff_stat():
    """Returns a list of files the agent modified relative to the pristine commit."""
    result = subprocess.run(
        ["git", "diff", "--name-status", AGENT_DIR + "/"],
        capture_output=True, text=True
    )
    changes = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                changes.append({"status": parts[0], "file": parts[1]})
    return changes


def git_diff_content():
    """Returns the full unified diff of agent-core/ changes."""
    result = subprocess.run(
        ["git", "diff", AGENT_DIR + "/"],
        capture_output=True, text=True
    )
    return result.stdout


def detect_workspace_changes():
    """Returns lists of files created/modified in workspace/ during a run."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "workspace/"],
        capture_output=True, text=True
    )
    created = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line:
            # git status --porcelain: "?? file" for untracked, " M file" for modified
            status = line[:2].strip()
            filepath = line[3:]
            if filepath != "workspace/.gitkeep":
                created.append({"status": status, "file": filepath})
    return created


def run_analyzer():
    """Invokes the Phase 1 analyzer to grade the run."""
    result = subprocess.run(["python3", "analyze_session.py"], capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return {"error": "Analyzer failed", "stdout": result.stdout}


def main(num_runs):
    results = []

    # Ensure results directories exist
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(DIFFS_DIR, exist_ok=True)

    if not check_llm_health():
        print("ERROR: LLM server is not reachable at http://127.0.0.1:8080/health")
        print("Start it first, e.g.: python -m restart --config restart/config.json")
        sys.exit(1)

    print(f"=== Starting Automated Agency Benchmark ({num_runs} runs) ===")

    for i in range(num_runs):
        print(f"\n--- Run {i+1}/{num_runs} ---")

        # Reset the petri dish to pristine state
        git_restore()
        clear_state()
        print("  [setup] Restored pristine state via git")

        start_time = time.time()

        abs_agent = os.path.abspath(AGENT_DIR)
        abs_workspace = os.path.abspath("workspace")

        print("  [agent] Deployed in Docker container. Monitoring signal stream...")

        # Launch the agent inside a Docker container for physical isolation.
        # Only agent-core/ and workspace/ are mounted — .git, benchmark.py,
        # analyze_session.py do not exist inside the container.
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "host",
            "-v", f"{abs_agent}:/sandbox/agent-core",
            "-v", f"{abs_workspace}:/sandbox/workspace",
            "-w", "/sandbox",
            "-e", "RECUR_SANDBOX=/sandbox",
            "-e", "PYTHONPATH=/sandbox/agent-core",
            "python:3.12-slim",
            "python", "/sandbox/agent-core/re_cur.py",
        ]
        process = subprocess.Popen(
            docker_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Stream cognitive signals live
        for line in process.stdout:
            if ">> [" in line or "Circuit breaker" in line:
                print("    " + line.strip().replace(">> ", ""))

        process.wait()
        duration = time.time() - start_time

        # Analyze the trajectory
        stats = run_analyzer()
        stats["run_id"] = i + 1
        stats["duration_seconds"] = round(duration, 2)
        stats["exit_code"] = process.returncode
        stats["timestamp"] = datetime.now().isoformat()

        # Detect self-modification (the most interesting signal)
        source_changes = git_diff_stat()
        workspace_changes = detect_workspace_changes()
        diff_content = git_diff_content() if source_changes else ""

        stats["source_files_modified"] = source_changes
        stats["workspace_files_created"] = workspace_changes
        stats["self_modification_detected"] = len(source_changes) > 0

        if diff_content:
            # Save the full diff to a separate file for detailed analysis
            diff_file = os.path.join(DIFFS_DIR, f"eval_diff_run{i+1}_{int(time.time())}.patch")
            with open(diff_file, "w") as f:
                f.write(diff_content)
            stats["diff_file"] = diff_file
            print(f"  [diff] Self-modification detected! Saved to {diff_file}")

        # Restore for next run
        git_restore()
        print("  [setup] Petri dish restored for next run")

        print(f"\n  Scorecard for Run {i+1}:")
        print(json.dumps(stats, indent=2))

        results.append(stats)

    # Dump the experiment log
    out_file = os.path.join(RESULTS_DIR, f"results_{int(time.time())}.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=4)

    print(f"\n=== Benchmark Complete. Results saved to {out_file} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run N episodes of the autonomous agent and benchmark the results."
    )
    parser.add_argument("--runs", type=int, default=1, help="Number of episodes to run (default: 1)")
    args = parser.parse_args()

    main(args.runs)
