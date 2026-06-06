#!/usr/bin/env bash
# =============================================================================
# 测试 2: 多轮对话 — "帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"
#
# 用法:
#   cd server && bash tests/test_agent_search/test_multi_turn.sh
#   BASE_URL=http://localhost:8080 bash tests/test_agent_search/test_multi_turn.sh
# =============================================================================

set -euo pipefail

# 加载共享工具函数
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SCRIPT_DIR}/_utils.sh"

# ---- 测试用例 ----

test_multi_turn() {
    divider
    echo "  测试 2: 多轮对话 — "帮我推荐跑鞋" → "要轻量的" → "预算 500 以内""
    divider

    local cid
    cid=$(new_conversation)
    ok "conversation_id: ${cid}"

    local pass=true

    # Turn 1: 帮我推荐跑鞋
    info "━━━ Turn 1 ━━━"
    local tmp1
    tmp1=$(mktemp /tmp/test_search_mt1_XXXXXX.sse)
    sse_search "帮我推荐跑鞋" "$cid" "$tmp1"
    print_sse_summary "$tmp1"
    if ! grep -q 'event: products' "$tmp1"; then
        fail "Turn 1 失败: 缺少 products 事件"
        pass=false
    fi
    rm -f "$tmp1"

    sleep 2

    # Turn 2: 要轻量的
    info "━━━ Turn 2 ━━━"
    local tmp2
    tmp2=$(mktemp /tmp/test_search_mt2_XXXXXX.sse)
    sse_search "要轻量的" "$cid" "$tmp2"
    print_sse_summary "$tmp2"
    if ! grep -q 'event: products' "$tmp2"; then
        fail "Turn 2 失败: 缺少 products 事件"
        pass=false
    fi
    rm -f "$tmp2"

    sleep 2

    # Turn 3: 预算 500 以内
    info "━━━ Turn 3 ━━━"
    local tmp3
    tmp3=$(mktemp /tmp/test_search_mt3_XXXXXX.sse)
    sse_search "预算 500 以内" "$cid" "$tmp3"
    print_sse_summary "$tmp3"
    if ! grep -q 'event: products' "$tmp3"; then
        fail "Turn 3 失败: 缺少 products 事件"
        pass=false
    fi
    rm -f "$tmp3"

    if $pass; then
        ok "测试 2 通过: 三轮对话全部有 products 事件"
    else
        fail "测试 2 失败"
    fi
}

# ---- 主入口 ----

main() {
    divider
    echo "  多轮对话测试"
    echo "  服务地址: ${BASE_URL}"
    divider

    precheck
    test_multi_turn

    divider
    echo "  测试完成"
    divider
}

main "$@"
