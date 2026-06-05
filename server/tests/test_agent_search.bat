@echo off
REM =============================================================================
REM Agent 搜索服务集成测试脚本 (Windows Batch)
REM =============================================================================
REM 测试 /api/search Agent 工作流的三个对话样例：
REM   1. 单轮对话："200 元以下的蓝牙耳机有哪些？"
REM   2. 多轮对话："帮我推荐跑鞋" -> "要轻量的" -> "预算 500 以内"
REM   3. 场景化推荐："下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"
REM
REM 用法:
REM   cd server
REM   tests\test_agent_search.bat
REM   或指定服务地址:
REM   set BASE_URL=http://localhost:8080 && tests\test_agent_search.bat
REM
REM 前置依赖 (Windows):
REM   - curl.exe  (Windows 10+ 系统自带)
REM   - powershell.exe (用于 JSON 解析，系统自带)
REM =============================================================================

setlocal enabledelayedexpansion

REM ---- 配置 ----
if "%BASE_URL%"=="" set "BASE_URL=http://127.0.0.1:8000"
if "%TIMEOUT%"=="" set "TIMEOUT=60"

set "RED=[31m"
set "GREEN=[32m"
set "YELLOW=[33m"
set "CYAN=[36m"
set "NC=[0m"

REM ---- 工具函数 ----

REM 获取新的 conversation_id
REM 使用 PowerShell 解析 JSON (Windows 系统自带)
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
:wait_done
timeout /T 2 /NOBREAK >nul
set /a waited+=2

REM 检查输出文件是否有 done 事件
findstr /C:"event: done" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 goto :wait_done_ok

REM 检查 curl 是否还在运行
tasklist /FI "IMAGENAME eq curl.exe" 2>nul | findstr "curl.exe" >nul 2>&1
if errorlevel 1 goto :wait_done_ok

if !waited! LSS %TIMEOUT% goto :wait_done

:wait_done_ok
REM 等待 curl 进程完全退出
timeout /T 1 /NOBREAK >nul
REM 清理残留 curl 进程 (仅清理本测试用的)
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

REM products 事件计数
set "count=0"
for /f %%a in ('findstr /C:"event: products" "!OUTFILE!" 2^>nul ^| find /C "event: products"') do set "count=%%a"
echo   products 事件: !count! 次

REM chat_reply 事件
findstr /C:"event: chat_reply" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    echo   -- chat_reply --
    REM 使用 PowerShell 解析 chat_reply 内容
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $cap = $false; foreach ($l in $lines) {" ^
        "  if ($l -eq 'event: chat_reply') { $cap = $true; continue }" ^
        "  if ($cap) { if ($l -match '^^event: ') { $cap = $false; continue }" ^
        "    if ($l -match '^^data:') { Write-Host '  | ' $l.Substring(5).Trim('\"') } } }"
    echo   ---------------
)

REM done 事件
findstr /C:"event: done" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    echo.
    REM 提取 done 的 data 行
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: done');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  done:' $lines[$idx+1].Substring(5) }"
)

REM next_options
findstr /C:"event: next_options" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: next_options');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  next_options:' $lines[$idx+1].Substring(5) }"
)

REM error
findstr /C:"event: error" "!OUTFILE!" >nul 2>&1
if not errorlevel 1 (
    powershell -NoProfile -Command ^
        "$lines = Get-Content '!OUTFILE!'; $idx = [array]::IndexOf($lines, 'event: error');" ^
        "if ($idx -ge 0 -and $idx+1 -lt $lines.Count) { Write-Host '  error:' $lines[$idx+1].Substring(5) }"
)

echo   ---------------------------------------------
endlocal
exit /b 0


REM ==================== 测试 1: 单轮对话 ====================
:test_single_turn
echo.
echo ================================================================================
echo   测试 1: 单轮对话 - "200 元以下的蓝牙耳机有哪些？"
echo ================================================================================

call :new_conversation
echo [OK]    conversation_id: %cid%

set "TMPFILE=%TEMP%\test_search_1_%RANDOM%.sse"
call :sse_search "200 元以下的蓝牙耳机有哪些？" "%cid%" "%TMPFILE%"
call :print_sse_summary "%TMPFILE%"

findstr /C:"event: products" "%TMPFILE%" >nul 2>&1
if not errorlevel 1 (
    echo [OK]    测试 1 通过: products 事件存在
) else (
    echo [FAIL]  测试 1 失败: 缺少 products 事件
)

del /F /Q "%TMPFILE%" >nul 2>&1
goto :eof


REM ==================== 测试 2: 多轮对话 ====================
:test_multi_turn
echo.
echo ================================================================================
echo   测试 2: 多轮对话 - "帮我推荐跑鞋" -> "要轻量的" -> "预算 500 以内"
echo ================================================================================

call :new_conversation
echo [OK]    conversation_id: %cid%

set "pass=1"

REM Turn 1
echo [INFO]  --- Turn 1 ---
set "TMP1=%TEMP%\test_search_2a_%RANDOM%.sse"
call :sse_search "帮我推荐跑鞋" "%cid%" "%TMP1%"
call :print_sse_summary "%TMP1%"
findstr /C:"event: products" "%TMP1%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Turn 1 失败: 缺少 products 事件
    set "pass=0"
)
del /F /Q "%TMP1%" >nul 2>&1

timeout /T 2 /NOBREAK >nul

REM Turn 2
echo [INFO]  --- Turn 2 ---
set "TMP2=%TEMP%\test_search_2b_%RANDOM%.sse"
call :sse_search "要轻量的" "%cid%" "%TMP2%"
call :print_sse_summary "%TMP2%"
findstr /C:"event: products" "%TMP2%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Turn 2 失败: 缺少 products 事件
    set "pass=0"
)
del /F /Q "%TMP2%" >nul 2>&1

timeout /T 2 /NOBREAK >nul

REM Turn 3
echo [INFO]  --- Turn 3 ---
set "TMP3=%TEMP%\test_search_2c_%RANDOM%.sse"
call :sse_search "预算 500 以内" "%cid%" "%TMP3%"
call :print_sse_summary "%TMP3%"
findstr /C:"event: products" "%TMP3%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Turn 3 失败: 缺少 products 事件
    set "pass=0"
)
del /F /Q "%TMP3%" >nul 2>&1

if "%pass%"=="1" (
    echo [OK]    测试 2 通过: 三轮对话全部有 products 事件
) else (
    echo [FAIL]  测试 2 失败
)
goto :eof


REM ==================== 测试 3: 场景化推荐 ====================
:test_scenario
echo.
echo ================================================================================
echo   测试 3: 场景化推荐 - "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案"
echo ================================================================================

call :new_conversation
echo [OK]    conversation_id: %cid%

set "TMPFILE=%TEMP%\test_search_3_%RANDOM%.sse"
call :sse_search "下周去三亚度假，帮我搭配一套从防晒到穿搭的方案" "%cid%" "%TMPFILE%"
call :print_sse_summary "%TMPFILE%"

for /f %%a in ('findstr /C:"event: products" "%TMPFILE%" 2^>nul ^| find /C "event: products"') do set "pc=%%a"
if %pc% GEQ 1 (
    echo [OK]    测试 3 通过: %pc% 个 products 事件
) else (
    echo [FAIL]  测试 3 失败: 缺少 products 事件
)

del /F /Q "%TMPFILE%" >nul 2>&1
goto :eof


REM ---- 主入口 ----
:main
echo.
echo ================================================================================
echo   AuraCart Agent 搜索服务集成测试 (Windows Batch)
echo   服务地址: %BASE_URL%
echo ================================================================================

echo [INFO]  检查服务可达性...
curl.exe -sS --connect-timeout 5 "%BASE_URL%/health" >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  服务不可达: %BASE_URL%/health
    echo.
    echo   请先启动服务: cd server ^&^& python run.py
    exit /b 1
)
echo [OK]    服务可达

REM 检查 curl.exe
where curl.exe >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  未找到 curl.exe，Windows 10+ 系统应自带此工具
    exit /b 1
)

REM 运行测试
call :test_single_turn
call :test_multi_turn
call :test_scenario

echo.
echo ================================================================================
echo   测试完成
echo ================================================================================

endlocal
goto :eof

REM 启动入口
call :main
