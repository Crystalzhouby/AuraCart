#!/bin/bash
# ============================================================
# claude-test-fix.sh — Run full test suite & auto-fix failures
# ============================================================
# Usage:
#   ./scripts/claude-test-fix.sh            # from server/ dir
#   bash scripts/claude-test-fix.sh         # from server/ dir
#
# What it does:
#   Invokes Claude Code to run pytest, analyze all failures,
#   and fix them one at a time. Tests are re-run after each fix
#   to verify the fix works before moving to the next failure.
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

echo "==> Claude Code: Run tests and auto-fix failures"
echo "    Project root: $PROJECT_ROOT"
echo ""

claude -p \
  "Run pytest in the server/ directory, analyze all failures, and fix them one at a time. Run tests after each fix to confirm the fix works before moving to the next failure. Do NOT modify tests to make them pass — fix the production code instead." \
  --allowedTools "Edit,Read,Bash,Grep" \
  --output-format stream-json
