#!/bin/bash
# ============================================================
# claude-implement.sh — Implement code from a plan document
# ============================================================
# Usage:
#   ./scripts/claude-implement.sh             # default: CON_PLAN.md
#   ./scripts/claude-implement.sh PLAN.md     # custom plan file
#   bash scripts/claude-implement.sh          # from server/ dir
#
# What it does:
#   Invokes Claude Code to read the specified plan document and
#   implement code according to it. The agent is allowed to run
#   tests, check git status, make commits as progress is made,
#   and edit source files.
#
# Prerequisites:
#   - claude CLI installed and authenticated
#   - A plan document (CON_PLAN.md, PLAN.md, etc.) exists under server/docs/
#   - Working directory must be the project root (not server/)
# ============================================================
set -euo pipefail

# Resolve project root (parent of this script's directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Plan file: first argument or default to server/docs/CON_PLAN.md
PLAN_FILE="${1:-server/docs/CON_PLAN.md}"

if [ ! -f "$PLAN_FILE" ]; then
    echo "ERROR: Plan file not found: $PLAN_FILE"
    echo "Usage: $0 [plan-file-path]"
    exit 1
fi

echo "==> Claude Code: Implement from plan"
echo "    Project root: $PROJECT_ROOT"
echo "    Plan file:    $PLAN_FILE"
echo ""

claude -p \
  "Read ${PLAN_FILE} and implement the code according to the plan. Write tests first (TDD), then implement minimal code to pass. Run tests after each implementation step. Use Git to check status or make commits as progress is made." \
  --allowedTools "Read,Edit,Write,Glob,Grep,Bash" \
  --output-format stream-json
