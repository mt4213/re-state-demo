#!/bin/bash

LLM_MODEL=$(grep '^LLM_MODEL=' agent-core/.env | cut -d '=' -f 2)
MODEL_FILENAME=$(basename "$LLM_MODEL")

if [[ "$MODEL_FILENAME" != *".gguf" ]]; then
    MODEL_FILENAME="${MODEL_FILENAME}.gguf"
fi

docker rm -f recur-llama-daemon 2>/dev/null

exec docker run --rm --name recur-llama-daemon --gpus all \
  -v /home/user_a/llama/models:/models \
  -p 8080:8080 ghcr.io/ggml-org/llama.cpp:server-cuda \
  -m "/models/${MODEL_FILENAME}" \
  --port 8080 --host 0.0.0.0 -c 8042 -n 900 --n-gpu-layers 16 \
  --batch-size 512 \
  --parallel 1 --defrag-thold 0.1 -fa on
