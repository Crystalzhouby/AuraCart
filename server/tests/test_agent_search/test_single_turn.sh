#!/usr/bin/env bash
# =============================================================================
# 测试 1: 单轮对话 — "推荐一款200元以下的防晒霜" + "推荐一款不含酒精的防晒霜"
#
# 用法:
#   cd server && bash tests/test_agent_search/test_single_turn.sh
#   BASE_URL=http://localhost:8080 bash tests/test_agent_search/test_single_turn.sh
# =============================================================================

set -euo pipefail

# 加载共享工具函数
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SCRIPT_DIR}/_utils.sh"

# ---- 测试用例 ----

test_single_turn() {
    divider
    echo "  测试 1: 单轮对话 (2 个查询)"
    divider

    local pass=true

    # --- 查询 1a: 推荐一款200元以下的防晒霜 ---
    echo ""
    info "--- 查询 1a: \"推荐一款200元以下的防晒霜\" ---"
    local cid
    cid=$(new_conversation)
    ok "conversation_id: ${cid}"

    local tmpfile
    tmpfile=$(mktemp /tmp/test_search_1a_XXXXXX.sse)
    sse_search "推荐一款200元以下的防晒霜" "$cid" "$tmpfile"
    print_sse_summary "$tmpfile"

    if grep -q 'event: welcome' "$tmpfile"; then
        ok "查询 1a: welcome 事件存在"
    else
        fail "查询 1a: 缺少 welcome 事件"
        pass=false
    fi
    if grep -q 'event: products' "$tmpfile"; then
        ok "查询 1a: products 事件存在"
    else
        fail "查询 1a: 缺少 products 事件"
        pass=false
    fi
    if grep -q 'event: done' "$tmpfile" 2>/dev/null && grep -A1 'event: done' "$tmpfile" | grep -q '"text"'; then
        ok "查询 1a: done 事件含结束语 text"
    else
        fail "查询 1a: done 事件缺少结束语 text"
        pass=false
    fi
    if grep -q 'event: next_options' "$tmpfile"; then
        ok "查询 1a: next_options 事件存在"
    else
        fail "查询 1a: 缺少 next_options 事件"
        pass=false
    fi
    rm -f "$tmpfile"

    sleep 2

    # --- 查询 1b: 推荐一款不含酒精的防晒霜 ---
    echo ""
    info "--- 查询 1b: \"推荐一款不含酒精的防晒霜\" ---"
    cid=$(new_conversation)
    ok "conversation_id: ${cid}"

    tmpfile=$(mktemp /tmp/test_search_1b_XXXXXX.sse)
    sse_search "推荐一款不含酒精的防晒霜" "$cid" "$tmpfile"
    print_sse_summary "$tmpfile"

    if grep -q 'event: welcome' "$tmpfile"; then
        ok "查询 1b: welcome 事件存在"
    else
        fail "查询 1b: 缺少 welcome 事件"
        pass=false
    fi
    if grep -q 'event: products' "$tmpfile"; then
        ok "查询 1b: products 事件存在"
    else
        fail "查询 1b: 缺少 products 事件"
        pass=false
    fi
    if grep -q 'event: done' "$tmpfile" 2>/dev/null && grep -A1 'event: done' "$tmpfile" | grep -q '"text"'; then
        ok "查询 1b: done 事件含结束语 text"
    else
        fail "查询 1b: done 事件缺少结束语 text"
        pass=false
    fi
    if grep -q 'event: next_options' "$tmpfile"; then
        ok "查询 1b: next_options 事件存在"
    else
        fail "查询 1b: 缺少 next_options 事件"
        pass=false
    fi
    rm -f "$tmpfile"

    if $pass; then
        ok "测试 1 通过"
    else
        fail "测试 1 失败"
    fi
}

# ---- 主入口 ----

main() {
    divider
    echo "  单轮对话测试"
    echo "  服务地址: ${BASE_URL}"
    divider

    precheck
    test_single_turn

    divider
    echo "  测试完成"
    divider
}

main "$@"
