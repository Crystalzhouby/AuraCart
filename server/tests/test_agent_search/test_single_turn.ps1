<#
.SYNOPSIS
    测试 1: 单轮对话 — "推荐一款200元以下的防晒霜" + "推荐一款不含酒精的防晒霜"

.EXAMPLE
    cd server
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_single_turn.ps1
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_single_turn.ps1 -BaseUrl "http://localhost:8080"
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Timeout = 300
)

$ErrorActionPreference = "Stop"

# dot-source 共享工具函数
. "$PSScriptRoot\_utils.ps1" -BaseUrl $BaseUrl -Timeout $Timeout

# ---- 测试用例 ----

function Test-SingleTurn {
    Write-Divider
    Write-Host "  测试 1: 单轮对话 (2 个查询)"
    Write-Divider

    $pass = $true

    # --- 查询 1a: 推荐一款200元以下的防晒霜 ---
    Write-Host ""
    Write-Info "--- 查询 1a: `"推荐一款200元以下的防晒霜`" ---"
    $cid = New-Conversation
    Write-Ok "conversation_id: ${cid}"

    $tmpfile = Join-Path $env:TEMP "test_search_1a_$(Get-Random).sse"
    Invoke-SseSearch -Query "推荐一款200元以下的防晒霜" -ConversationId $cid -OutFile $tmpfile
    Write-SseSummary $tmpfile

    if (-not (Select-String -Path $tmpfile -Pattern 'event: welcome' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "查询 1a: 缺少 welcome 事件"; $pass = $false
    }
    if (Select-String -Path $tmpfile -Pattern 'event: products' -Quiet -ErrorAction SilentlyContinue) {
        Write-Ok "查询 1a: products 事件存在"
    } else {
        Write-Fail "查询 1a: 缺少 products 事件"; $pass = $false
    }
    if (-not (Select-String -Path $tmpfile -Pattern 'event: next_options' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "查询 1a: 缺少 next_options 事件"; $pass = $false
    } else {
        Write-Ok "查询 1a: next_options 事件存在"
    }
    Remove-Item $tmpfile -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 2

    # --- 查询 1b: 推荐一款不含酒精的防晒霜 ---
    Write-Host ""
    Write-Info "--- 查询 1b: `"推荐一款不含酒精的防晒霜`" ---"
    $cid = New-Conversation
    Write-Ok "conversation_id: ${cid}"

    $tmpfile = Join-Path $env:TEMP "test_search_1b_$(Get-Random).sse"
    Invoke-SseSearch -Query "推荐一款不含酒精的防晒霜" -ConversationId $cid -OutFile $tmpfile
    Write-SseSummary $tmpfile

    if (-not (Select-String -Path $tmpfile -Pattern 'event: welcome' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "查询 1b: 缺少 welcome 事件"; $pass = $false
    }
    if (Select-String -Path $tmpfile -Pattern 'event: products' -Quiet -ErrorAction SilentlyContinue) {
        Write-Ok "查询 1b: products 事件存在"
    } else {
        Write-Fail "查询 1b: 缺少 products 事件"; $pass = $false
    }
    if (-not (Select-String -Path $tmpfile -Pattern 'event: next_options' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "查询 1b: 缺少 next_options 事件"; $pass = $false
    } else {
        Write-Ok "查询 1b: next_options 事件存在"
    }
    Remove-Item $tmpfile -Force -ErrorAction SilentlyContinue

    if ($pass) {
        Write-Ok "测试 1 通过"
    } else {
        Write-Fail "测试 1 失败"
    }
}

# ---- 主入口 ----

function Main {
    Write-Divider
    Write-Host "  单轮对话测试"
    Write-Host "  服务地址: ${BaseUrl}"
    Write-Divider

    Test-Precheck
    Test-SingleTurn

    Write-Divider
    Write-Host "  测试完成"
    Write-Divider
}

Main
