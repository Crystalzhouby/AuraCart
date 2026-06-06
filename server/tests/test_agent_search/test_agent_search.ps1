<#
.SYNOPSIS
    Agent 搜索服务集成测试 — 运行全部三个场景 (Windows PowerShell)

.DESCRIPTION
    依次运行以下三个测试场景：
      1. 单轮对话："推荐一款200元以下的防晒霜" + "推荐一款不含酒精的防晒霜"
      2. 多轮对话："帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"
      3. 场景化推荐："下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"

.PARAMETER BaseUrl
    服务地址，默认 http://127.0.0.1:8000

.PARAMETER Timeout
    单次请求超时秒数，默认 300

.EXAMPLE
    cd server
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_agent_search.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_agent_search.ps1 -BaseUrl "http://localhost:8080"

.EXAMPLE
    # 单独运行某个场景:
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_single_turn.ps1
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_multi_turn.ps1
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search/test_scenario.ps1
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Timeout = 300
)

$ErrorActionPreference = "Stop"

# dot-source 共享工具函数
. "$PSScriptRoot\_utils.ps1" -BaseUrl $BaseUrl -Timeout $Timeout

# ---- 测试用例（委托给独立脚本） ----

function Test-SingleTurn {
    & "$PSScriptRoot\test_single_turn.ps1" -BaseUrl $BaseUrl -Timeout $Timeout
}

function Test-MultiTurn {
    & "$PSScriptRoot\test_multi_turn.ps1" -BaseUrl $BaseUrl -Timeout $Timeout
}

function Test-Scenario {
    & "$PSScriptRoot\test_scenario.ps1" -BaseUrl $BaseUrl -Timeout $Timeout
}

# ---- 主入口 ----

function Main {
    Write-Divider
    Write-Host "  AuraCart Agent 搜索服务集成测试 (Windows PowerShell)"
    Write-Host "  服务地址: ${BaseUrl}"
    Write-Divider

    Test-Precheck
    Test-SingleTurn
    Test-MultiTurn
    Test-Scenario

    Write-Divider
    Write-Host "  全部测试完成"
    Write-Divider
}

Main
