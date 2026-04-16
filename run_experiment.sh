#!/bin/bash
# Wrapper script to run the autonomous agency benchmark

RUNS=${1:-1}

echo "============================================="
echo "  ContReAct Evaluation Pipeline              "
echo "============================================="

# Ensure the LLM server is accessible
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health)

if [ "$STATUS" != "200" ]; then
    echo "[!] LLM Server is offline."
    echo "Starting LLM server in the background..."
    python3 -m restart --config restart/config.json > logs/restart_daemon.log 2>&1 &
    DAEMON_PID=$!
    
    echo "Waiting for LLM server to boot (this takes a few seconds)..."
    while [ "$STATUS" != "200" ]; do
        sleep 2
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health || echo "000")
    done
    echo "[+] LLM Server is ONLINE."
else
    echo "[+] LLM Server is already ONLINE."
    DAEMON_PID=""
fi

echo ""
echo "Initiating $RUNS run(s)..."
python3 benchmark.py --runs $RUNS
BENCHMARK_STATUS=$?

if [ -n "$DAEMON_PID" ]; then
    echo ""
    echo "Cleaning up local LLM daemon (PID: $DAEMON_PID)..."
    kill -SIGTERM $DAEMON_PID
    # Also clean up the docker container specifically defined in config
    docker rm -f recur-llama-daemon 2>/dev/null
fi

echo "Done."
exit $BENCHMARK_STATUS