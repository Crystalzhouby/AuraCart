<#
.SYNOPSIS
    测试 2: 多轮对话 — "帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"

.EXAMPLE
    cd server
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_multi_turn.ps1
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_multi_turn.ps1 -BaseUrl "http://localhost:8080"
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Timeout = 300
)

$ErrorActionPreference = "Stop"

# dot-source 共享工具函数
. "$PSScriptRoot\_utils.ps1" -BaseUrl $BaseUrl -Timeout $Timeout

# ---- 测试用例 ----

function Test-MultiTurn {
    Write-Divider
    Write-Host "  测试 2: 多轮对话 - `"帮我推荐跑鞋`" -> `"要轻量的`" -> `"预算 500 以内`""
    Write-Divider

    $cid = New-Conversation
    Write-Ok "conversation_id: ${cid}"

    $pass = $true

    # Turn 1: 帮我推荐跑鞋
    Write-Info "--- Turn 1 ---"
    $tmp1 = Join-Path $env:TEMP "test_search_mt1_$(Get-Random).sse"
    Invoke-SseSearch -Query "帮我推荐跑鞋" -ConversationId $cid -OutFile $tmp1
    Write-SseSummary $tmp1
    if (-not (Select-String -Path $tmp1 -Pattern 'event: products' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "Turn 1 失败: 缺少 products 事件"
        $pass = $false
    }
    Remove-Item $tmp1 -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 2

    # Turn 2: 要轻量的
    Write-Info "--- Turn 2 ---"
    $tmp2 = Join-Path $env:TEMP "test_search_mt2_$(Get-Random).sse"
    Invoke-SseSearch -Query "要轻量的" -ConversationId $cid -OutFile $tmp2
    Write-SseSummary $tmp2
    if (-not (Select-String -Path $tmp2 -Pattern 'event: products' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "Turn 2 失败: 缺少 products 事件"
        $pass = $false
    }
    Remove-Item $tmp2 -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 2

    # Turn 3: 预算 500 以内
    Write-Info "--- Turn 3 ---"
    $tmp3 = Join-Path $env:TEMP "test_search_mt3_$(Get-Random).sse"
    Invoke-SseSearch -Query "预算 500 以内" -ConversationId $cid -OutFile $tmp3
    Write-SseSummary $tmp3
    if (-not (Select-String -Path $tmp3 -Pattern 'event: products' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "Turn 3 失败: 缺少 products 事件"
        $pass = $false
    }
    Remove-Item $tmp3 -Force -ErrorAction SilentlyContinue

    if ($pass) {
        Write-Ok "测试 2 通过: 三轮对话全部有 products 事件"
    } else {
        Write-Fail "测试 2 失败"
    }
}

# ---- 主入口 ----

function Main {
    Write-Divider
    Write-Host "  多轮对话测试"
    Write-Host "  服务地址: ${BaseUrl}"
    Write-Divider

    Test-Precheck
    Test-MultiTurn

    Write-Divider
    Write-Host "  测试完成"
    Write-Divider
}

Main
