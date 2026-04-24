#!/bin/bash
# Wrapper script to run the autonomous agency benchmark
# Assumes LLM server is already running manually

RUNS=${1:-1}

# Define the UI script name and port
REVIEW_SCRIPT="re_view.py" # Change this if your python file is named differently
REVIEW_PORT="5050"

echo "============================================="
echo "            Evaluation Pipeline              "
echo "============================================="

echo "[*] Checking UI status..."

# 1. Check if the UI is already running via its /health endpoint
UI_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$REVIEW_PORT/health)

if [ "$UI_STATUS" -eq 200 ]; then
    echo "[+] UI is already running on port $REVIEW_PORT."
else
    echo "[*] UI not found. Starting $REVIEW_SCRIPT in the background..."
    
    # Start the python script in the background using '&'
    # '> /dev/null 2>&1' hides its output so it doesn't clutter your terminal
    python3 "$REVIEW_SCRIPT" > /dev/null 2>&1 &
    
    # Give the HTTP server 1.5 seconds to bind to the port and start
    sleep 1.5
    
    # Verify it actually started
    UI_STATUS_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$REVIEW_PORT/health)
    if [ "$UI_STATUS_CHECK" -eq 200 ]; then
        echo "[+] UI successfully started."
    else
        echo "[-] WARNING: UI did not respond after starting. (Check if port is blocked or script has errors)"
    fi
fi

echo "---------------------------------------------"

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