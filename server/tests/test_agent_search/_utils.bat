@echo off
REM =============================================================================
REM Agent 搜索服务集成测试 — 共享工具函数
REM 用法: call _utils.bat :label [args...]
REM =============================================================================

REM ---- 配置 ----
if "%BASE_URL%"=="" set "BASE_URL=http://127.0.0.1:8000"
if "%TIMEOUT%"=="" set "TIMEOUT=300"

REM ---- 工具函数 ----

REM 获取新的 conversation_id（设置 %cid% 变量）
:new_conversation
set "cid="
for /f "delims=" %%a in ('powershell -NoProfile -Command "try { (Invoke-RestMethod -Uri '%BASE_URL%/api/conversation' -Method Get -TimeoutSec 5).conversation_id } catch { exit 1 }" 2^>nul') do set "cid=%%a"
if "%cid%"=="" (
    echo [FAIL]  无法连接 %BASE_URL%/api/conversation，请确认服务已启动
    exit /b 1
)
exit /b 0

REM 执行一次 SSE 搜索，输出到文件
REM 参数: %1=query, %2=conversation_id, %3=outfile
:sse_search
setlocal
set "QUERY=%~1"
set "CID=%~2"
set "OUTFILE=%~3"

echo [INFO]  查询: %QUERY%

REM URL 编码 (使用 PowerShell)
for /f "delims=" %%a in ('powershell -NoProfile -Command "[System.Uri]::EscapeDataString('!QUERY!')"') do set "ENC_QUERY=%%a"

set "URI=%BASE_URL%/api/search/!CID!?q=!ENC_QUERY!&stream=true"

REM 后台启动 curl SSE 请求
start /B "" curl.exe -sS -N --connect-timeout 5 --max-time %TIMEOUT% ^
    -H "Accept: text/event-stream" ^
    -o "!OUTFILE!" "!URI!" >nul 2>&1

REM 等待 done 事件或超时
set "waited=0"
:sse_wait
timeout /T 2 /NOBREAK >nul
set /a waited+=2
findstr /C:"event: done" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 goto :sse_done
tasklist /FI "IMAGENAME eq curl.exe" 2>nul | findstr "curl.exe" >nul 2>&1
if errorlevel 1 goto :sse_done
if !waited! LSS %TIMEOUT% goto :sse_wait

:sse_done
timeout /T 1 /NOBREAK >nul
taskkill /F /IM curl.exe 2>nul >nul
endlocal
exit /b 0

REM 打印 SSE 事件摘要
REM 参数: %1=outfile
:print_sse_summary
setlocal
set "OUTFILE=%~1"

echo.
echo [INFO]  SSE 事件汇总:
echo   ---------------------------------------------

findstr /C:"event: welcome" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: welcome');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  welcome:' $lines[$idx+1].Substring(5).Trim('\"') }"
)

set "count=0"
for /f %%a in ('findstr /C:"event: products" "!OUTFILE!" 2^>nul ^| find /C "event: products"') do set "count=%%a"
echo   products 事件: !count! 次

findstr /C:"event: chat_reply" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    echo   -- chat_reply --
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $cap = $false; foreach ($l in $lines) {" ^
        "  if ($l -eq 'event: chat_reply') { $cap = $true; continue }" ^
        "  if ($cap) { if ($l -match '^^event: ') { $cap = $false; continue }" ^
        "    if ($l -match '^^data:') { Write-Host '  | ' $l.Substring(5).Trim('\"') } } }"
    echo   ---------------
)

findstr /C:"event: done" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    echo.
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: done');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  done:' $lines[$idx+1].Substring(5) }"
)

findstr /C:"event: next_options" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: next_options');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  next_options:' $lines[$idx+1].Substring(5) }"
)

findstr /C:"event: error" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: error');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  error:' $lines[$idx+1].Substring(5) }"
)

echo   ---------------------------------------------
endlocal
exit /b 0

REM 前置检查
:precheck
echo [INFO]  检查服务可达性...
curl.exe -sS --connect-timeout 5 "%BASE_URL%/health" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  服务不可达: %BASE_URL%/health
    echo.
    echo   请先启动服务: cd server ^&^& python run.py
    exit /b 1
)
echo [OK]    服务可达

where curl.exe >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  未找到 curl.exe，Windows 10+ 系统应自带此工具
    exit /b 1
)
exit /b 0
