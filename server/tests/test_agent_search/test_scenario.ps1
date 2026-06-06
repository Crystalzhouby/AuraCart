<#
.SYNOPSIS
    测试 3: 场景化推荐 — "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"

.EXAMPLE
    cd server
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_scenario.ps1
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_scenario.ps1 -BaseUrl "http://localhost:8080"
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Timeout = 300
)

$ErrorActionPreference = "Stop"

# dot-source 共享工具函数
. "$PSScriptRoot\_utils.ps1" -BaseUrl $BaseUrl -Timeout $Timeout

# ---- 测试用例 ----

function Test-Scenario {
    Write-Divider
    Write-Host "  测试 3: 场景化推荐 - `"下周去三亚度假，帮我搭配一套从防晒到穿搭的方案`""
    Write-Divider

    $cid = New-Conversation
    Write-Ok "conversation_id: ${cid}"

    $tmpfile = Join-Path $env:TEMP "test_search_3_$(Get-Random).sse"
    Invoke-SseSearch -Query "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案" -ConversationId $cid -OutFile $tmpfile
    Write-SseSummary $tmpfile

    $pc = (Select-String -Path $tmpfile -Pattern 'event: products' -ErrorAction SilentlyContinue).Count
    $pass = $true
    if ($pc -ge 1) {
        Write-Ok "${pc} 个 products 事件"
    } else {
        Write-Fail "缺少 products 事件"; $pass = $false
    }
    if (-not (Select-String -Path $tmpfile -Pattern 'event: welcome' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "缺少 welcome 事件"; $pass = $false
    }
    if (-not (Select-String -Path $tmpfile -Pattern 'event: next_options' -Quiet -ErrorAction SilentlyContinue)) {
        Write-Fail "缺少 next_options 事件"; $pass = $false
    }
    if ($pass) {
        Write-Ok "测试 3 通过"
    } else {
        Write-Fail "测试 3 失败"
    }

    Remove-Item $tmpfile -Force -ErrorAction SilentlyContinue
}

# ---- 主入口 ----

function Main {
    Write-Divider
    Write-Host "  场景化推荐测试"
    Write-Host "  服务地址: ${BaseUrl}"
    Write-Divider

    Test-Precheck
    Test-Scenario

    Write-Divider
    Write-Host "  测试完成"
    Write-Divider
}

Main
