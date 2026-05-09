#!/usr/bin/env bash
# Wrapper script to run the autonomous agency benchmark

set -e # Exit on error

# ==========================================
# Configuration & Variables
# ==========================================
RUNS=${1:-1}
REVIEW_SCRIPT="re_view/re_view.py"
REVIEW_PORT="5050"
REVIEW_URL="http://127.0.0.1:${REVIEW_PORT}"
ENV_FILE=".env"

# ==========================================
# Helper Functions
# ==========================================
get_env() {
    local key=$1
    local default=$2
    if [ -f "$ENV_FILE" ]; then
        # POSIX compliant grep/cut/sed
        val=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | sed 's/^[ "\'\''\t]*//;s/[ "\'\''\t]*$//')
        if [ -n "$val" ]; then
            echo "$val"
        else
            echo "$default"
        fi
    else
        echo "$default"
    fi
}

check_health() {
    local url=$1
    # Returns the HTTP status code using standard curl
    curl -s -o /dev/null -w "%{http_code}" "$url/health"
}

# ==========================================
# Main Execution
# ==========================================
LLM_BASE_URL=$(get_env "LLM_BASE_URL" "http://127.0.0.1:8080")

echo "============================================="
echo "            Evaluation Pipeline              "
echo "============================================="

# 1. Start UI
echo "[*] Checking UI status..."
UI_STATUS=$(check_health "$REVIEW_URL")

if [ "$UI_STATUS" = "200" ]; then
    echo "[+] UI is already running."
else
    echo "[*] UI not found. Starting..."
    ./venv/bin/python3 "$REVIEW_SCRIPT" > /dev/null 2>&1 &
    sleep 1.5
    
    if [ "$(check_health "$REVIEW_URL")" = "200" ]; then
        echo "[+] UI successfully started."
    else
        echo "[!] WARNING: UI failed to start."
    fi
fi

# 2. Start LLM Server
echo "---------------------------------------------"
echo "[*] Checking LLM Server at $LLM_BASE_URL..."

if [ "$(check_health "$LLM_BASE_URL")" != "200" ]; then
    echo "[!] LLM Server is offline. Starting..."
    ./llama_run.sh > /tmp/llama_run.log 2>&1 &
    
    echo -n "[*] Waiting for LLM server."
    for i in $(seq 1 30); do
        sleep 2
        echo -n "."
        if [ "$(check_health "$LLM_BASE_URL")" = "200" ]; then
            echo " [+] ONLINE."
            break
        fi
    done
else
    echo "[+] LLM Server is ONLINE."
fi

# 3. Run Benchmark
echo "Initiating $RUNS run(s)..."
./venv/bin/python3 benchmark.py --runs "$RUNS"
echo "Done."