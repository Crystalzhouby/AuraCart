#!/usr/bin/env bash
# =============================================================================
# Agent 搜索服务集成测试 — 运行全部三个场景
# =============================================================================
#
# 用法:
#   cd server && bash tests/test_agent_search/test_agent_search.sh
#   BASE_URL=http://localhost:8080 bash tests/test_agent_search/test_agent_search.sh
#
# 单独运行某个场景:
#   bash tests/test_agent_search/test_single_turn.sh    # 测试 1: 单轮对话
#   bash tests/test_agent_search/test_multi_turn.sh     # 测试 2: 多轮对话
#   bash tests/test_agent_search/test_scenario.sh       # 测试 3: 场景化推荐
# =============================================================================

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SCRIPT_DIR}/_utils.sh"

# ---- 测试用例（调用同目录下的独立脚本） ----

test_single_turn() {
    bash "${_SCRIPT_DIR}/test_single_turn.sh"
}

test_multi_turn() {
    bash "${_SCRIPT_DIR}/test_multi_turn.sh"
}

test_scenario() {
    bash "${_SCRIPT_DIR}/test_scenario.sh"
}

# ---- 主入口 ----

main() {
    divider
    echo "  AuraCart Agent 搜索服务集成测试"
    echo "  服务地址: ${BASE_URL}"
    divider

    precheck
    test_single_turn
    test_multi_turn
    test_scenario

    divider
    echo "  全部测试完成"
    divider
}

main "$@"
