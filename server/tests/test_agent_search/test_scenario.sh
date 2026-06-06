#!/usr/bin/env bash
# =============================================================================
# 测试 3: 场景化推荐 — "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"
#
# 用法:
#   cd server && bash tests/test_agent_search/test_scenario.sh
#   BASE_URL=http://localhost:8080 bash tests/test_agent_search/test_scenario.sh
# =============================================================================

set -euo pipefail

# 加载共享工具函数
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SCRIPT_DIR}/_utils.sh"

# ---- 测试用例 ----

test_scenario() {
    divider
    echo "  测试 3: 场景化推荐 — "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案""
    divider

    local cid
    cid=$(new_conversation)
    ok "conversation_id: ${cid}"

    local tmpfile
    tmpfile=$(mktemp /tmp/test_search_3_XXXXXX.sse)
    sse_search "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案" "$cid" "$tmpfile"
    print_sse_summary "$tmpfile"

    # 场景化推荐预期多品类 → 多个 products 事件 + welcome + next_options
    local pass=true
    local pc
    pc=$(grep -c 'event: products' "$tmpfile" 2>/dev/null || echo 0)
    if [[ $pc -ge 1 ]]; then
        ok "${pc} 个 products 事件"
    else
        fail "缺少 products 事件"
        pass=false
    fi
    if grep -q 'event: welcome' "$tmpfile"; then
        ok "welcome 事件存在"
    else
        fail "缺少 welcome 事件"
        pass=false
    fi
    if grep -q 'event: next_options' "$tmpfile"; then
        ok "next_options 事件存在"
    else
        fail "缺少 next_options 事件"
        pass=false
    fi

    if $pass; then
        ok "测试 3 通过"
    else
        fail "测试 3 失败"
    fi

    rm -f "$tmpfile"
}

# ---- 主入口 ----

main() {
    divider
    echo "  场景化推荐测试"
    echo "  服务地址: ${BASE_URL}"
    divider

    precheck
    test_scenario

    divider
    echo "  测试完成"
    divider
}

main "$@"
