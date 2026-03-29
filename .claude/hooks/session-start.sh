#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo "Installing AI Marketplace dependencies..."
pip install -e ".[dev]" --quiet
echo "Dependencies installed."
