#!/usr/bin/env bash
# =============================================================================
# Agent 搜索服务集成测试 — 共享工具函数（非独立执行，供各 test_*.sh 引用）
# =============================================================================

# ---- 配置（可通过环境变量覆盖） ----
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
TIMEOUT="${TIMEOUT:-300}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- 输出函数 ----

divider() {
    echo ""
    printf '%*s\n' "80" '' | tr ' ' '═'
    echo ""
}

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# ---- 工具函数 ----

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
        "${BASE_URL}/api/search/${cid}?q=$(python3 -c 'import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))' "$query")&stream=true" \
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

# 前置检查：服务可达 + jq 可用
precheck() {
    info "检查服务可达性..."
    if ! curl -sS --connect-timeout 5 "${BASE_URL}/health" > /dev/null 2>&1; then
        fail "服务不可达: ${BASE_URL}/health"
        echo ""
        echo "  请先启动服务: cd server && python run.py"
        exit 1
    fi
    ok "服务可达"

    if ! command -v jq &>/dev/null; then
        warn "未安装 jq，部分解析功能可能受限"
    fi
    if ! command -v python3 &>/dev/null; then
        fail "未找到 python3，URL 编码需要 Python 3"
        exit 1
    fi
}
