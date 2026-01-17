#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-0}"

export LLM_PROVIDER="openai"
# export OPENAI_API_KEY=""
export OPENAI_BASE_URL="https://api.openai.com"
export CHAT_MODEL_NAME="gpt-4o"
export EXTRACTOR_MODEL_NAME="gpt-4o"
export SYSTEM_MODE="$MODE"

python app.py
