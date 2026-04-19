#!/bin/bash
# Wrapper script to run the autonomous agency benchmark
# Assumes LLM server is already running manually

RUNS=${1:-1}

echo "============================================="
echo "  ContReAct Evaluation Pipeline              "
echo "============================================="

# Ensure the LLM server is accessible
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health)

if [ "$STATUS" != "200" ]; then
    echo "[!] LLM Server is offline."
    echo "Please start the LLM server manually, then run this script again."
    exit 1
fi

echo "[+] LLM Server is ONLINE."
echo ""
echo "Initiating $RUNS run(s)..."
python3 benchmark.py --runs $RUNS

echo "Done."
