#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-0}"

export LLM_PROVIDER="openai"
export OPENAI_BASE_URL="https://api.openai.com"
export CHAT_MODEL_NAME="gpt-3.5-turbo"
export EXTRACTOR_MODEL_NAME="gpt-3.5-turbo"
export SYSTEM_MODE="$MODE"

python app.py
