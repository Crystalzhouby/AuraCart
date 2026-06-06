#!/usr/bin/env bash
# =============================================================================
# Agent 搜索服务集成测试脚本 (macOS)
# =============================================================================
# 测试 /api/search Agent 工作流的三个对话样例：
#   1. 单轮对话："200 元以下的蓝牙耳机有哪些？"
#   2. 多轮对话："帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"
#   3. 场景化推荐："下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"
#
# 用法:
#   cd server && bash tests/test_agent_search.sh
#   或指定服务地址:
#   BASE_URL=http://localhost:8080 bash tests/test_agent_search.sh
#
# 依赖: curl, jq (解析 JSON)
# =============================================================================

set -euo pipefail

# ---- 配置 ----
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
TIMEOUT="${TIMEOUT:-60}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- 工具函数 ----

divider() {
    echo ""
    printf '%*s\n' "80" '' | tr ' ' '═'
    echo ""
}

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# 获取新的 conversation_id
new_conversation() {
    local resp
    resp=$(curl -sS --connect-timeout 5 "${BASE_URL}/api/conversation" 2>/dev/null) || {
        fail "无法连接 ${BASE_URL}/api/conversation，请确认服务已启动"
        exit 1
    }
    local cid
    cid=$(echo "$resp" | jq -r '.conversation_id // empty')
    if [[ -z "$cid" ]]; then
        fail "获取 conversation_id 失败: $resp"
        exit 1
    fi
    echo "$cid"
}

# 执行一次 SSE 搜索，将事件流输出到指定文件
# 参数: query, conversation_id, output_file
sse_search() {
    local query="$1"
    local cid="$2"
    local outfile="$3"

    info "查询: ${query}"

    curl -sS -N --connect-timeout 5 --max-time "$TIMEOUT" \
        -H "Accept: text/event-stream" \
        "${BASE_URL}/api/search?q=$(python3 -c 'import urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$query")&stream=true&conversation_id=${cid}" \
        > "$outfile" 2>/dev/null &

    local pid=$!

    # 等待 done 事件或超时
    local waited=0
    local interval=2
    while [[ $waited -lt $TIMEOUT ]]; do
        sleep "$interval"
        waited=$((waited + interval))
        if grep -q 'event: done' "$outfile" 2>/dev/null; then
            break
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
    done

    # 确保进程结束
    if kill -0 "$pid" 2>/dev/null; then
        sleep 1
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
}

# 解析并打印 SSE 事件摘要
print_sse_summary() {
    local outfile="$1"

    echo ""
    info "SSE 事件汇总:"
    echo "  ──────────────────────────────────────────────"

    # welcome 事件
    if grep -q 'event: welcome' "$outfile" 2>/dev/null; then
        echo -n "  welcome: "
        grep -A1 'event: welcome' "$outfile" | grep '^data:' | sed 's/^data://' | sed 's/^"//' | sed 's/"$//'
    fi

    # products 事件（逐商品单对象）
    local product_count
    product_count=$(grep -c 'event: products' "$outfile" 2>/dev/null || true)
    echo "  products 事件: ${product_count} 次"

    # chat_reply 事件（收集文本）
    if grep -q 'event: chat_reply' "$outfile" 2>/dev/null; then
        echo "  ── chat_reply ──"
        grep -A1 'event: chat_reply' "$outfile" | grep '^data:' | \
            sed 's/^data://' | sed 's/^"//' | sed 's/"$//' | \
            fold -w 76 -s | sed 's/^/  | /'
        echo "  ───────────────"
    fi

    # done 事件（含 text 结束语）
    if grep -q 'event: done' "$outfile" 2>/dev/null; then
        echo ""
        echo -n "  done: "
        grep -A1 'event: done' "$outfile" | grep '^data:' | sed 's/^data://'
    fi

    # next_options
    if grep -q 'event: next_options' "$outfile" 2>/dev/null; then
        echo -n "  next_options: "
        grep -A1 'event: next_options' "$outfile" | grep '^data:' | sed 's/^data://'
    fi

    # error
    if grep -q 'event: error' "$outfile" 2>/dev/null; then
        echo -n "  error: "
        grep -A1 'event: error' "$outfile" | grep '^data:' | sed 's/^data://'
    fi

    echo "  ──────────────────────────────────────────────"
}

# ---- 测试用例 ----

# ==================== 测试 1: 单轮对话 ====================
test_single_turn() {
    divider
    echo "  测试 1: 单轮对话 — "200 元以下的蓝牙耳机有哪些？""
    divider

    local cid
    cid=$(new_conversation)
    ok "conversation_id: ${cid}"

    local tmpfile
    tmpfile=$(mktemp /tmp/test_search_1_XXXXXX.sse)
    sse_search "200 元以下的蓝牙耳机有哪些？" "$cid" "$tmpfile"
    print_sse_summary "$tmpfile"

    # 检查关键事件
    local pass=true
    if grep -q 'event: welcome' "$tmpfile"; then
        ok "welcome 事件存在"
    else
        fail "缺少 welcome 事件"
        pass=false
    fi
    if grep -q 'event: products' "$tmpfile"; then
        ok "products 事件存在"
    else
        fail "缺少 products 事件"
        pass=false
    fi
    if grep -q 'event: done' "$tmpfile" 2>/dev/null && grep -A1 'event: done' "$tmpfile" | grep -q '"text"'; then
        ok "done 事件含结束语 text"
    else
        fail "done 事件缺少结束语 text"
        pass=false
    fi
    if grep -q 'event: next_options' "$tmpfile"; then
        ok "next_options 事件存在"
    else
        fail "缺少 next_options 事件"
        pass=false
    fi

    if $pass; then
        ok "测试 1 通过"
    else
        fail "测试 1 失败"
    fi

    rm -f "$tmpfile"
}

# ==================== 测试 2: 多轮对话 ====================
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
    tmp1=$(mktemp /tmp/test_search_2a_XXXXXX.sse)
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
    tmp2=$(mktemp /tmp/test_search_2b_XXXXXX.sse)
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
    tmp3=$(mktemp /tmp/test_search_2c_XXXXXX.sse)
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

# ==================== 测试 3: 场景化推荐 ====================
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
    echo "  AuraCart Agent 搜索服务集成测试"
    echo "  服务地址: ${BASE_URL}"
    divider

    # 前置检查
    info "检查服务可达性..."
    if ! curl -sS --connect-timeout 5 "${BASE_URL}/health" > /dev/null 2>&1; then
        fail "服务不可达: ${BASE_URL}/health"
        echo ""
        echo "  请先启动服务: cd server && python run.py"
        exit 1
    fi
    ok "服务可达"

    # 检查 jq
    if ! command -v jq &>/dev/null; then
        warn "未安装 jq，部分解析功能可能受限"
    fi

    # 运行测试
    test_single_turn
    test_multi_turn
    test_scenario

    divider
    echo "  测试完成"
    divider
}

main "$@"
