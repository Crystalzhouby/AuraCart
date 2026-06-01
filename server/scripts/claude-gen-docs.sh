#!/bin/bash
# ============================================================
# claude-gen-docs.sh — Generate project documentation
# ============================================================
# Usage:
#   ./scripts/claude-gen-docs.sh          # from server/ dir
#   bash scripts/claude-gen-docs.sh       # from server/ dir
#
# What it does:
#   Invokes Claude Code to scan the entire codebase and generate
#   (or update) README.md and API.md under the delivery/ folder.
#   Documents are based on actual implementation, not speculation.
#
# Prerequisites:
#   - claude CLI installed and authenticated
#   - Working directory must be the project root (not server/)
# ============================================================
set -euo pipefail

# Resolve project root (parent of this script's directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "==> Claude Code: Generate API docs from codebase"
echo "    Project root: $PROJECT_ROOT"
echo ""

claude -p \
  "Generate README.md and API.md from this codebase and save them to the delivery/ folder. Read the actual source code — do NOT fabricate endpoints, schemas, or features that don't exist. API.md must include: HTTP method, path, query parameters, request/response examples, and error codes for every endpoint." \
  --allowedTools "Read,Glob,Write" \
  --output-format stream-json
