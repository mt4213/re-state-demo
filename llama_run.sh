#!/bin/bash

get_env() {
    local key=$1
    local default=$2
    val=$(grep "^${key}=" /home/user_a/projects/sandbox/.env 2>/dev/null | cut -d '=' -f 2- | sed 's/#.*$//' | tr -d ' ')
    echo "${val:-$default}"
}

LLM_PORT=$(get_env "LLM_PORT" "8080")
LLM_CTX_SIZE=$(get_env "LLM_CTX_SIZE" "8192")
LLM_MAX_GENERATION=$(get_env "LLM_MAX_GENERATION" "2048")
LLM_GPU_LAYERS=$(get_env "LLM_GPU_LAYERS" "25")
LLM_BATCH_SIZE=$(get_env "LLM_BATCH_SIZE" "512")
LLM_PARALLEL=$(get_env "LLM_PARALLEL" "1")
LLM_DEFRAG_THOLD=$(get_env "LLM_DEFRAG_THOLD" "0.1")
LLM_FLASH_ATTENTION=$(get_env "LLM_FLASH_ATTENTION" "on")

LLM_MODEL=$(grep '^LLM_MODEL=' /home/user_a/projects/sandbox/.env | cut -d '=' -f 2)
MODELS_BASE="/home/user_a/llama/models"
MODEL_PATH="${MODELS_BASE}/${LLM_MODEL}"

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "ERROR: Model not found at $MODEL_PATH"
    exit 1
fi

echo "Starting llama-server: $LLM_MODEL on port $LLM_PORT"
echo "Model path: $MODEL_PATH"

exec /home/user_a/llama/cpp/build/bin/llama-server \
  -m "$MODEL_PATH" \
  --port ${LLM_PORT} --host 0.0.0.0 \
  -c ${LLM_CTX_SIZE} \
  -n ${LLM_MAX_GENERATION} \
  --n-gpu-layers ${LLM_GPU_LAYERS} \
  --batch-size ${LLM_BATCH_SIZE} \
  --parallel ${LLM_PARALLEL} \
  --defrag-thold ${LLM_DEFRAG_THOLD} \
  --flash-attn ${LLM_FLASH_ATTENTION} \
  --ubatch-size ${LLM_BATCH_SIZE} \
  --no-mmap \
  --mlock
