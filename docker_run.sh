#!/bin/bash

get_env() {
    local key=$1
    local default=$2
    local val=$(grep "^${key}=" agent-core/.env 2>/dev/null | cut -d '=' -f 2-)
    echo "${val:-$default}"
}

LLM_PORT=$(get_env "LLM_PORT" "8080")
LLM_CTX_SIZE=$(get_env "LLM_CTX_SIZE" "8192")
LLM_MAX_GENERATION=$(get_env "LLM_MAX_GENERATION" "2048")
LLM_GPU_LAYERS=$(get_env "LLM_GPU_LAYERS" "25")
LLM_BATCH_SIZE=$(get_env "LLM_BATCH_SIZE" "1024")
LLM_PARALLEL=$(get_env "LLM_PARALLEL" "1")
LLM_DEFRAG_THOLD=$(get_env "LLM_DEFRAG_THOLD" "0.1")
LLM_FLASH_ATTENTION=$(get_env "LLM_FLASH_ATTENTION" "on")

LLM_MODEL=$(grep '^LLM_MODEL=' agent-core/.env | cut -d '=' -f 2)
MODEL_FILENAME=$(basename "$LLM_MODEL")

if [[ "$MODEL_FILENAME" != *".gguf" ]]; then
    MODEL_FILENAME="${MODEL_FILENAME}.gguf"
fi

docker rm -f recur-llama-daemon 2>/dev/null

exec docker run --rm --name recur-llama-daemon --gpus all \
  -v /home/user_a/llama/models:/models \
  -p ${LLM_PORT}:${LLM_PORT} ghcr.io/ggml-org/llama.cpp:server-cuda \
  -m "/models/${MODEL_FILENAME}" \
  --port ${LLM_PORT} --host 0.0.0.0 -c ${LLM_CTX_SIZE} -n ${LLM_MAX_GENERATION} --n-gpu-layers ${LLM_GPU_LAYERS} \
  --batch-size ${LLM_BATCH_SIZE} \
  --parallel ${LLM_PARALLEL} --defrag-thold ${LLM_DEFRAG_THOLD} -fa ${LLM_FLASH_ATTENTION}
