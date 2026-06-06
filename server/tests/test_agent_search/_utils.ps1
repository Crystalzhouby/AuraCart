<#
.SYNOPSIS
    Agent 搜索服务集成测试 — 共享工具函数（dot-source 引用）
#>

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Timeout = 300
)

$ErrorActionPreference = "Stop"

# ---- 输出函数 ----

function Write-Divider {
    Write-Host ""
    Write-Host ("=" * 80)
    Write-Host ""
}

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "[OK]    $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Fail  { Write-Host "[FAIL]  $args" -ForegroundColor Red }

# ---- 工具函数 ----

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

function Invoke-SseSearch {
    param(
        [string]$Query,
        [string]$ConversationId,
        [string]$OutFile
    )

    Write-Info "查询: ${Query}"

    $encodedQuery = [System.Uri]::EscapeDataString($Query)
    $uri = "${BaseUrl}/api/search/${ConversationId}?q=${encodedQuery}&stream=true"

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

    if (-not $proc.HasExited) {
        Start-Sleep -Seconds 1
        try { $proc.Kill() } catch { }
        $proc.WaitForExit(1000) | Out-Null
    }
}

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

    # welcome 事件
    $welcomeIdx = [array]::IndexOf($lines, 'event: welcome')
    if ($welcomeIdx -ge 0 -and ($welcomeIdx + 1) -lt $lines.Count) {
        $welcomeData = $lines[$welcomeIdx + 1] -replace '^data:', '' -replace '^"', '' -replace '"$', ''
        Write-Host "  welcome: ${welcomeData}"
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

function Test-Precheck {
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

    $curlPath = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curlPath) {
        Write-Warn "未找到 curl.exe，Windows 10+ 系统应自带此工具"
        exit 1
    }
}
