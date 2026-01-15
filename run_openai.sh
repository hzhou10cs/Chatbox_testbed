#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-0}"

export LLM_PROVIDER="openai"
export OPENAI_API_KEY="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"
export OPENAI_BASE_URL="https://api.openai.com"
export CHAT_MODEL_NAME="gpt-3.5-turbo"
export EXTRACTOR_MODEL_NAME="gpt-3.5-turbo"
export SYSTEM_MODE="$MODE"

python app.py
