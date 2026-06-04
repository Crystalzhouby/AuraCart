<#
.SYNOPSIS
    Agent 搜索服务集成测试脚本 (Windows PowerShell)

.DESCRIPTION
    测试 /api/search Agent 工作流的三个对话样例：
      1. 单轮对话："200 元以下的蓝牙耳机有哪些？"
      2. 多轮对话："帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"
      3. 场景化推荐："下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"

.PARAMETER BaseUrl
    服务地址，默认 http://127.0.0.1:8000

.PARAMETER Timeout
    单次请求超时秒数，默认 60

.EXAMPLE
    cd server
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tests/test_agent_search.ps1 -BaseUrl "http://localhost:8080"

.NOTES
    前置依赖: curl.exe (Windows 10+ 系统自带)
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Timeout = 60
)

$ErrorActionPreference = "Stop"

# ---- 工具函数 ----

function Write-Divider {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host ""
}

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Fail  { Write-Host "[FAIL]  $args" -ForegroundColor Red }

# 获取新的 conversation_id
function New-Conversation {
    try {
        $resp = Invoke-RestMethod -Uri "$BaseUrl/api/conversation" -Method Get -TimeoutSec 5
        $cid = $resp.conversation_id
        if (-not $cid) {
            Write-Fail "获取 conversation_id 失败: 响应中无 conversation_id 字段"
            exit 1
        }
        return $cid
    } catch {
        Write-Fail "无法连接 $BaseUrl/api/conversation，请确认服务已启动"
        Write-Host "  $($_.Exception.Message)"
        exit 1
    }
}

# 执行一次 SSE 搜索，将事件流输出到指定文件
function Invoke-SseSearch {
    param(
        [string]$Query,
        [string]$ConversationId,
        [string]$OutFile
    )

    Write-Info "查询: ${Query}"

    $encodedQuery = [System.Uri]::EscapeDataString($Query)
    $uri = "${BaseUrl}/api/search?q=${encodedQuery}&stream=true&conversation_id=${ConversationId}"

    # 使用 curl.exe 进行 SSE 流式请求 (Windows 10+ 内置)
    $curlArgs = @(
        "-sS", "-N",
        "--connect-timeout", "5",
        "--max-time", "$Timeout",
        "-H", "Accept: text/event-stream",
        "-o", $OutFile,
        $uri
    )

    $proc = Start-Process -FilePath "curl.exe" `
        -ArgumentList $curlArgs `
        -NoNewWindow `
        -PassThru

    # 等待 done 事件或超时
    $waited = 0
    $interval = 2
    while ($waited -lt $Timeout) {
        Start-Sleep -Seconds $interval
        $waited += $interval

        if (Test-Path $OutFile) {
            $found = Select-String -Path $OutFile -Pattern 'event: done' -Quiet -ErrorAction SilentlyContinue
            if ($found) { break }
        }

        if ($proc.HasExited) { break }
    }

    # 确保进程结束
    if (-not $proc.HasExited) {
        Start-Sleep -Seconds 1
        try { $proc.Kill() } catch { }
        $proc.WaitForExit(1000) | Out-Null
    }
}

# 解析并打印 SSE 事件摘要
function Write-SseSummary {
    param([string]$OutFile)

    if (-not (Test-Path $OutFile)) {
        Write-Warn "输出文件不存在: $OutFile"
        return
    }

    Write-Host ""
    Write-Info "SSE 事件汇总:"
    Write-Host "  " + ("-" * 45)

    $lines = @(Get-Content $OutFile -ErrorAction SilentlyContinue)
    if ($lines.Count -eq 0) {
        Write-Warn "输出文件为空"
        return
    }

    # products 事件
    $productCount = ($lines | Where-Object { $_ -eq 'event: products' }).Count
    Write-Host "  products 事件: ${productCount} 次"

    # chat_reply 事件
    if ($lines -contains 'event: chat_reply') {
        Write-Host "  -- chat_reply --"
        $capture = $false
        foreach ($line in $lines) {
            if ($line -eq 'event: chat_reply') { $capture = $true; continue }
            if ($capture) {
                if ($line -match '^event: ') { $capture = $false; continue }
                if ($line -match '^data:') {
                    $text = $line -replace '^data:', '' -replace '^"', '' -replace '"$', ''
                    Write-Host "  | $text"
                }
            }
        }
        Write-Host "  ---------------"
    }

    # done 事件
    $doneIdx = [array]::IndexOf($lines, 'event: done')
    if ($doneIdx -ge 0 -and ($doneIdx + 1) -lt $lines.Count) {
        Write-Host ""
        $doneData = $lines[$doneIdx + 1] -replace '^data:', ''
        Write-Host "  done: ${doneData}"
    }

    # next_options
    $nextIdx = [array]::IndexOf($lines, 'event: next_options')
    if ($nextIdx -ge 0 -and ($nextIdx + 1) -lt $lines.Count) {
        $nextData = $lines[$nextIdx + 1] -replace '^data:', ''
        Write-Host "  next_options: ${nextData}"
    }

    # error
    $errIdx = [array]::IndexOf($lines, 'event: error')
    if ($errIdx -ge 0 -and ($errIdx + 1) -lt $lines.Count) {
        $errData = $lines[$errIdx + 1] -replace '^data:', ''
        Write-Host "  error: ${errData}"
    }

    Write-Host "  " + ("-" * 45)
}

# ---- 测试用例 ----

# ==================== 测试 1: 单轮对话 ====================
function Test-SingleTurn {
    Write-Divider
    Write-Host "  测试 1: 单轮对话 - `"200 元以下的蓝牙耳机有哪些？`""
    Write-Divider

    $cid = New-Conversation
    Write-Ok "conversation_id: ${cid}"

    $tmpfile = Join-Path $env:TEMP "test_search_1_$(Get-Random).sse"
    Invoke-SseSearch -Query "200 元以下的蓝牙耳机有哪些？" -ConversationId $cid -OutFile $tmpfile
    Write-SseSummary $tmpfile

    if (Select-String -Path $tmpfile -Pattern 'event: products' -Quiet -ErrorAction SilentlyContinue) {
        Write-Ok "测试 1 通过: products 事件存在"
    } else {
        Write-Fail "测试 1 失败: 缺少 products 事件"
    }

    Remove-Item $tmpfile -Force -ErrorAction SilentlyContinue
}

# ==================== 测试 2: 多轮对话 ====================
function Test-MultiTurn {
    Write-Divider
    Write-Host "  测试 2: 多轮对话 - `"帮我推荐跑鞋`" -> `"要轻量的`" -> `"预算 500 以内`""
    Write-Divider

    $cid = New-Conversation
    Write-Ok "conversation_id: ${cid}"

    $pass = $true

    # Turn 1: 帮我推荐跑鞋
    Write-Info "--- Turn 1 ---"
    $tmp1 = Join-Path $env:TEMP "test_search_2a_$(Get-Random).sse"
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
    $tmp2 = Join-Path $env:TEMP "test_search_2b_$(Get-Random).sse"
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
    $tmp3 = Join-Path $env:TEMP "test_search_3c_$(Get-Random).sse"
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

# ==================== 测试 3: 场景化推荐 ====================
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
    if ($pc -ge 1) {
        Write-Ok "测试 3 通过: ${pc} 个 products 事件"
    } else {
        Write-Fail "测试 3 失败: 缺少 products 事件"
    }

    Remove-Item $tmpfile -Force -ErrorAction SilentlyContinue
}

# ---- 主入口 ----

function Main {
    Write-Divider
    Write-Host "  AuraCart Agent 搜索服务集成测试 (Windows PowerShell)"
    Write-Host "  服务地址: ${BaseUrl}"
    Write-Divider

    # 前置检查
    Write-Info "检查服务可达性..."
    try {
        $null = Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get -TimeoutSec 5
        Write-Ok "服务可达"
    } catch {
        Write-Fail "服务不可达: $BaseUrl/health"
        Write-Host ""
        Write-Host "  请先启动服务: cd server && python run.py"
        exit 1
    }

    # 检查 curl.exe
    $curlPath = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curlPath) {
        Write-Warn "未找到 curl.exe，Windows 10+ 系统应自带此工具"
        exit 1
    }

    # 运行测试
    Test-SingleTurn
    Test-MultiTurn
    Test-Scenario

    Write-Divider
    Write-Host "  测试完成"
    Write-Divider
}

Main
