#!/usr/bin/env bash
# Wrapper script to run the autonomous agency benchmark

# Exit immediately if a command exits with a non-zero status, and treat unset variables as an error
set -euo pipefail

# ==========================================
# Configuration & Variables
# ==========================================
RUNS=${1:-1}
REVIEW_SCRIPT="re_view/re_view.py"
REVIEW_PORT="5050"
REVIEW_URL="http://127.0.0.1:${REVIEW_PORT}"
ENV_FILE=".env" # Assumes .env is in the same directory as the script

# Colors for professional logging
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ==========================================
# Helper Functions
# ==========================================
log_info()    { echo -e "[*] $1"; }
log_success() { echo -e "${GREEN}[+] $1${NC}"; }
log_warn()    { echo -e "${YELLOW}[-] WARNING: $1${NC}"; }
log_error()   { echo -e "${RED}[!] ERROR: $1${NC}"; }

get_env() {
    local key=$1
    local default=$2
    # Safely extract env var without destroying spaces
    if [[ -f "$ENV_FILE" ]]; then
        local val
        val=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d '=' -f 2- | sed 's/^[ "\'\t]*//;s/[ "\'\t]*$//')
        echo "${val:-$default}"
    else
        echo "$default"
    fi
}

check_health() {
    local url=$1
    # Returns the HTTP status code (e.g., 200, 404, 000 if unreachable)
    curl -s -o /dev/null -w "%{http_code}" "$url/health" || echo "000"
}

# ==========================================
# Main Execution
# ==========================================
LLM_BASE_URL=$(get_env "LLM_BASE_URL" "http://127.0.0.1:8080")

echo "============================================="
echo "            Evaluation Pipeline              "
echo "============================================="

# -------------------------------------------
# 1. Start UI (Review Script)
# -------------------------------------------
log_info "Checking UI status..."

if [[ "$(check_health "$REVIEW_URL")" == "200" ]]; then
    log_success "UI is already running on port $REVIEW_PORT."
else
    log_info "UI not found. Starting $REVIEW_SCRIPT in the background..."
    
    python3 "$REVIEW_SCRIPT" > /dev/null 2>&1 &
    sleep 1.5 # Give HTTP server time to bind
    
    if [[ "$(check_health "$REVIEW_URL")" == "200" ]]; then
        log_success "UI successfully started."
    else
        log_warn "UI did not respond after starting. (Check if port is blocked or script has errors)"
    fi
fi

echo "---------------------------------------------"

# -------------------------------------------
# 2. Start LLM Server
# -------------------------------------------
log_info "Checking LLM Server at $LLM_BASE_URL..."

if [[ "$(check_health "$LLM_BASE_URL")" != "200" ]]; then
    log_error "LLM Server is offline. Starting..."
    ./llama_run.sh > /tmp/llama_run.log 2>&1 &
    
    log_info "Waiting for LLM server (max 60s)..."
    server_up=false
    
    for i in {1..30}; do
        if [[ "$(check_health "$LLM_BASE_URL")" == "200" ]]; then
            server_up=true
            break
        fi
        echo -n "."
        sleep 2
    done
    echo "" # Newline after dots

    if [[ "$server_up" == true ]]; then
        log_success "LLM Server is ONLINE."
    else
        log_error "LLM Server failed to start. Check /tmp/llama_run.log"
        exit 1
    fi
else
    log_success "LLM Server is ONLINE."
fi

echo "---------------------------------------------"

# -------------------------------------------
# 3. Run Benchmark
# -------------------------------------------
echo -e "\nInitiating $RUNS run(s)..."
python3 benchmark.py --runs "$RUNS"

log_success "Evaluation Pipeline Complete."